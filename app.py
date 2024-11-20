from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
from twilio.rest import Client
from dotenv import load_dotenv
import phonenumbers
from itsdangerous import URLSafeTimedSerializer
import re
from functools import wraps
import pytz

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'your-secret-key-here')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///missedcalls.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
app.config['SECURITY_PASSWORD_SALT'] = os.getenv('SECURITY_PASSWORD_SALT', 'your-salt-here')

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Email verification
serializer = URLSafeTimedSerializer(app.config['SECRET_KEY'])

# Security decorator for subscription check
def subscription_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if current_user.subscription_status not in ['active', 'trial']:
            flash('Please activate your subscription to access this feature.', 'error')
            return redirect(url_for('billing'))
        return f(*args, **kwargs)
    return decorated_function

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    business_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    backup_phone = db.Column(db.String(20))
    timezone = db.Column(db.String(50), default='UTC')
    sms_template = db.Column(db.Text, nullable=False, default="Thank you for calling {business_name}. We're sorry we missed your call. We'll get back to you as soon as possible.")
    custom_templates = db.relationship('SMSTemplate', backref='user', lazy=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    is_verified = db.Column(db.Boolean, default=False)
    subscription_status = db.Column(db.String(20), default='trial')
    trial_ends_at = db.Column(db.DateTime, default=lambda: datetime.utcnow() + timedelta(days=14))
    last_login = db.Column(db.DateTime)
    failed_login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime)
    missed_calls = db.relationship('MissedCall', backref='user', lazy=True)
    business_hours = db.relationship('BusinessHours', backref='user', lazy=True)

class SMSTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BusinessHours(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0 = Monday, 6 = Sunday
    open_time = db.Column(db.Time, nullable=False)
    close_time = db.Column(db.Time, nullable=False)
    is_closed = db.Column(db.Boolean, default=False)

class MissedCall(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    caller_number = db.Column(db.String(20), nullable=False)
    caller_name = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    duration = db.Column(db.Integer)  # Call duration in seconds
    sms_sent = db.Column(db.Boolean, default=False)
    sms_status = db.Column(db.String(20))
    sms_sent_at = db.Column(db.DateTime)
    template_used = db.Column(db.Text)
    notes = db.Column(db.Text)
    follow_up_status = db.Column(db.String(20), default='pending')
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# Initialize Twilio client
twilio_client = Client(os.getenv('TWILIO_ACCOUNT_SID'), os.getenv('TWILIO_AUTH_TOKEN'))

# Index route
@app.route('/')
def index():
    return render_template('index.html')

# Registration and Authentication Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        business_name = request.form.get('business_name')
        email = request.form.get('email')
        password = request.form.get('password')
        phone_number = request.form.get('phone_number')
        timezone = request.form.get('timezone')
        
        # Enhanced validation
        if not all([business_name, email, password, phone_number]):
            flash('All fields are required', 'error')
            return redirect(url_for('register'))
        
        # Password strength validation
        if not re.match(r'^(?=.*[A-Za-z])(?=.*\d)(?=.*[@$!%*#?&])[A-Za-z\d@$!%*#?&]{8,}$', password):
            flash('Password must be at least 8 characters and contain letters, numbers, and special characters', 'error')
            return redirect(url_for('register'))
        
        # Phone number validation
        try:
            phone = phonenumbers.parse(phone_number)
            if not phonenumbers.is_valid_number(phone):
                raise ValueError()
        except:
            flash('Invalid phone number format. Please use international format (e.g., +1234567890)', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(email=email).first():
            flash('Email already registered', 'error')
            return redirect(url_for('register'))
        
        if User.query.filter_by(phone_number=phone_number).first():
            flash('Phone number already registered', 'error')
            return redirect(url_for('register'))
        
        # Create new user with enhanced features
        new_user = User(
            business_name=business_name,
            email=email,
            password_hash=generate_password_hash(password),
            phone_number=phone_number,
            timezone=timezone or 'UTC',
            subscription_status='trial',
            trial_ends_at=datetime.utcnow() + timedelta(days=14)
        )
        
        # Add default business hours
        for day in range(7):  # 0 = Monday, 6 = Sunday
            hours = BusinessHours(
                user=new_user,
                day_of_week=day,
                open_time=datetime.strptime('09:00', '%H:%M').time(),
                close_time=datetime.strptime('17:00', '%H:%M').time(),
                is_closed=day in [5, 6]  # Closed on weekends by default
            )
            db.session.add(hours)
        
        # Add default SMS templates
        templates = [
            ('Default', "Thank you for calling {business_name}. We're sorry we missed your call. We'll get back to you as soon as possible."),
            ('After Hours', "Thank you for calling {business_name}. We're currently closed and will return your call during our business hours: {open_time} to {close_time}."),
            ('Weekend', "Thank you for calling {business_name}. We're closed for the weekend and will return your call on Monday."),
        ]
        
        for name, content in templates:
            template = SMSTemplate(
                name=name,
                content=content,
                user=new_user,
                is_active=name == 'Default'
            )
            db.session.add(template)
        
        try:
            db.session.add(new_user)
            db.session.commit()
            
            # Generate verification token
            token = serializer.dumps(email, salt=app.config['SECURITY_PASSWORD_SALT'])
            verification_url = url_for('verify_email', token=token, _external=True)
            
            # TODO: Send verification email
            print(f"Verification URL: {verification_url}")  # For development
            
            login_user(new_user)
            flash('Registration successful! Please verify your email address.', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            db.session.rollback()
            flash('An error occurred during registration. Please try again.', 'error')
            return redirect(url_for('register'))
    
    return render_template('register.html', timezones=pytz.common_timezones)

# Dashboard route with enhanced features
@app.route('/dashboard')
@login_required
def dashboard():
    # Get timezone-aware current time
    user_tz = pytz.timezone(current_user.timezone)
    now = datetime.now(user_tz)
    
    # Get recent missed calls with pagination
    page = request.args.get('page', 1, type=int)
    missed_calls = MissedCall.query.filter_by(user_id=current_user.id)\
        .order_by(MissedCall.timestamp.desc())\
        .paginate(page=page, per_page=10)
    
    # Calculate statistics
    total_calls = MissedCall.query.filter_by(user_id=current_user.id).count()
    today_calls = MissedCall.query.filter_by(user_id=current_user.id)\
        .filter(MissedCall.timestamp >= now.replace(hour=0, minute=0, second=0)).count()
    sms_sent = MissedCall.query.filter_by(user_id=current_user.id, sms_sent=True).count()
    
    # Get business hours for today
    today_hours = BusinessHours.query.filter_by(
        user_id=current_user.id,
        day_of_week=now.weekday()
    ).first()
    
    # Check subscription status
    days_left = 0
    if current_user.subscription_status == 'trial':
        days_left = (current_user.trial_ends_at - datetime.utcnow()).days
    
    return render_template('dashboard.html',
        missed_calls=missed_calls,
        total_calls=total_calls,
        today_calls=today_calls,
        sms_sent=sms_sent,
        today_hours=today_hours,
        days_left=days_left,
        current_time=now
    )

# SMS Template Management
@app.route('/templates', methods=['GET', 'POST'])
@login_required
@subscription_required
def manage_templates():
    if request.method == 'POST':
        name = request.form.get('name')
        content = request.form.get('content')
        
        if not all([name, content]):
            flash('Template name and content are required', 'error')
            return redirect(url_for('manage_templates'))
        
        template = SMSTemplate(
            name=name,
            content=content,
            user=current_user
        )
        
        try:
            db.session.add(template)
            db.session.commit()
            flash('Template added successfully!', 'success')
        except:
            db.session.rollback()
            flash('Error adding template', 'error')
        
        return redirect(url_for('manage_templates'))
    
    templates = SMSTemplate.query.filter_by(user_id=current_user.id).all()
    return render_template('templates.html', templates=templates)

# Business Hours Management
@app.route('/business-hours', methods=['GET', 'POST'])
@login_required
@subscription_required
def manage_hours():
    if request.method == 'POST':
        for day in range(7):
            is_closed = request.form.get(f'closed_{day}') == 'on'
            open_time = request.form.get(f'open_{day}')
            close_time = request.form.get(f'close_{day}')
            
            hours = BusinessHours.query.filter_by(
                user_id=current_user.id,
                day_of_week=day
            ).first()
            
            if hours:
                hours.is_closed = is_closed
                if not is_closed and open_time and close_time:
                    hours.open_time = datetime.strptime(open_time, '%H:%M').time()
                    hours.close_time = datetime.strptime(close_time, '%H:%M').time()
        
        try:
            db.session.commit()
            flash('Business hours updated successfully!', 'success')
        except:
            db.session.rollback()
            flash('Error updating business hours', 'error')
        
        return redirect(url_for('manage_hours'))
    
    hours = BusinessHours.query.filter_by(user_id=current_user.id).order_by(BusinessHours.day_of_week).all()
    return render_template('business_hours.html', hours=hours)

# Billing route
@app.route('/billing', methods=['GET', 'POST'])
@login_required
def billing():
    if request.method == 'POST':
        # Handle the one-time payment of $9.99
        try:
            # In a real application, you would integrate with a payment processor here
            current_user.has_paid = True
            current_user.trial_ends_at = None  # Remove trial end date since they've paid
            db.session.commit()
            flash('Thank you for your purchase! You now have lifetime access.', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash('Payment processing failed. Please try again.', 'error')
            return redirect(url_for('billing'))
    
    return render_template('billing.html', 
                         lifetime_price=9.99,
                         trial_days_left=(current_user.trial_ends_at - datetime.utcnow()).days if current_user.trial_ends_at else 0)

# Twilio webhook for missed calls
@app.route('/webhook/missed-call', methods=['POST'])
def missed_call_webhook():
    try:
        # Get call details from Twilio webhook
        caller_number = request.form.get('From', '')
        caller_name = request.form.get('CallerName', '')
        call_duration = request.form.get('CallDuration', 0)
        
        # Create missed call record
        missed_call = MissedCall(
            caller_number=caller_number,
            caller_name=caller_name,
            duration=call_duration,
            user_id=1  # Default user ID - you'll need to map this based on the called number
        )
        db.session.add(missed_call)
        db.session.commit()

        # Send SMS notification
        try:
            message = twilio_client.messages.create(
                body=f"Thank you for calling. We'll get back to you as soon as possible.",
                from_=request.form.get('To'),  # The number that was called
                to=caller_number
            )
            missed_call.sms_sent = True
            missed_call.sms_status = message.status
            missed_call.sms_sent_at = datetime.utcnow()
            db.session.commit()
        except Exception as e:
            app.logger.error(f"SMS sending failed: {str(e)}")

        return jsonify({'status': 'success', 'message': 'Missed call recorded'}), 200
    except Exception as e:
        app.logger.error(f"Webhook error: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Test route for Twilio
@app.route('/test-twilio')
def test_twilio():
    try:
        # Get account info to test credentials
        account = twilio_client.api.accounts(os.getenv('TWILIO_ACCOUNT_SID')).fetch()
        return jsonify({
            'status': 'success',
            'message': 'Twilio credentials are valid',
            'account_name': account.friendly_name
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 400

# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash('Logged in successfully!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password', 'error')
    
    return render_template('login.html')

# Logout route
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully', 'success')
    return redirect(url_for('index'))

# Settings route
@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create database tables
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, port=5002)
