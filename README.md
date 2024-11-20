# MissedCallSMS Service

A modern web application that helps businesses manage missed calls by automatically sending SMS responses to potential clients.

## Features

- User-friendly dashboard to track missed calls
- Automatic SMS responses to missed calls
- Customizable SMS templates
- Real-time analytics and reporting
- Secure user authentication
- Modern and responsive design

## Prerequisites

- Python 3.8 or higher
- Twilio account for SMS functionality
- pip (Python package manager)

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd missed-call-service
```

2. Create a virtual environment and activate it:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
cp .env.example .env
```
Edit the `.env` file with your configuration:
- Generate a secure SECRET_KEY
- Add your Twilio credentials (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN)

5. Initialize the database:
```bash
flask db upgrade
```

## Running the Application

1. Start the Flask development server:
```bash
flask run
```

2. Open your browser and navigate to `http://localhost:5000`

## Setting Up Twilio

1. Sign up for a Twilio account at https://www.twilio.com
2. Get your Account SID and Auth Token from the Twilio Console
3. Add these credentials to your `.env` file
4. Configure your Twilio phone number's webhook to point to your application's `/webhook/missed-call` endpoint

## Usage

1. Register your business account
2. Configure your SMS template in the settings
3. Start receiving missed calls and automatic SMS responses
4. Monitor call analytics from the dashboard

## Security

- All passwords are securely hashed
- Session management with Flask-Login
- CSRF protection enabled
- Environment variables for sensitive data

## Contributing

1. Fork the repository
2. Create a new branch
3. Make your changes
4. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
