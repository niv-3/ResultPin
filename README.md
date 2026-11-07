# 💳 KoboTap

A full-stack Django web application for purchasing digital services such as airtime, mobile data, cable TV subscriptions, electricity tokens, and educational services through secure wallet and card payments.

KoboTap demonstrates real-world backend engineering concepts including payment gateway integration, wallet accounting, transaction management, third-party API integration, and secure authentication.

---

## ✨ Features

- User registration with OTP email verification
- Secure login and authentication
- Wallet funding using Paystack
- Wallet-based service purchases
- Card payments via Paystack
- Airtime purchase
- Mobile data purchase
- Cable TV subscriptions
- Electricity bill payments
- Cashback rewards
- Wallet transaction history
- Automatic refund handling when provider requests fail
- Blog, FAQ and customer reviews
- Responsive user interface

---

## 🛠 Tech Stack

### Backend
- Python
- Django
- Django REST Framework

### Frontend
- HTML5
- CSS3
- JavaScript
- Bootstrap 5

### Database
- PostgreSQL
- SQLite (development)

### Payment Gateway
- Paystack

### Third-Party Services
- CheapDataHub API

---

## 🏗 Project Architecture

```
KoboTap
│
├── Authentication
├── Wallet System
├── Payment Processing
├── Service Management
├── Transaction Management
├── Vendor API Integration
└── User Dashboard
```

---

## Payment Flow

### Wallet Payment

```
User
   ↓
Wallet Balance
   ↓
Debit Wallet
   ↓
Provider API
   ↓
Success
or
Automatic Refund
```

### Card Payment

```
User
   ↓
Paystack
   ↓
Payment Verification
   ↓
Provider API
   ↓
Service Delivery
```

---

## Screenshots

Screenshots will be added after deployment.

---

## Installation

Clone the repository

```bash
git clone https://github.com/niv-3/ResultPin.git
```

Navigate into the project

```bash
cd ResultPin
```

Create a virtual environment

```bash
python -m venv venv
```

Activate it

Windows

```bash
venv\Scripts\activate
```

Install dependencies

```bash
pip install -r requirements.txt
```

Run migrations

```bash
python manage.py migrate
```

Start the development server

```bash
python manage.py runserver
```

---

## Environment Variables

Create a `.env` file in the project root.

Example:

```env
SECRET_KEY=your_secret_key

DEBUG=True

DATABASE_URL=sqlite:///db.sqlite3

PAYSTACK_PUBLIC_KEY=your_public_key
PAYSTACK_SECRET_KEY=your_secret_key

CHEAPDATAHUB_API_KEY=your_api_key

EMAIL_HOST_USER=example@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
```

---

## TV and electricity setup

1. Run `python manage.py migrate`.
2. Add `VTPASS_API_KEY` and `VTPASS_SECRET_KEY` to your local environment. Use
   `VTPASS_TEST_MODE=True` and `VTPASS_BILLS_ENABLED=True` in a test instance with
   a separate database and test wallet balances.
3. In Django admin, set the VTpass service ID on each active TV or electricity
   provider. For example, use `dstv` for DStv or `ikeja-electric` for Ikeja Electric.
   The category slugs are `tv` or `cable` for TV and `electricity` for electricity.
4. For TV, configure each plan's VTpass variation code and selling price. Use the
   provider's current variation list to populate the catalogue.
5. Check successful, rejected, and pending payments in the sandbox before setting
   `VTPASS_TEST_MODE=False` on the live instance with live credentials.

Customers pay from their KoboTap wallet and can reopen recent receipts to check
pending payments or retrieve prepaid tokens.

## Current Status

### Completed

- User authentication
- OTP verification
- Wallet funding
- Wallet payments
- Card payments
- Transaction verification
- Airtime purchases
- Data purchases
- Automatic wallet refunds
- Payment history

### Planned Improvements

- Improved dashboard analytics
- Better mobile responsiveness
- Additional payment providers
- Admin reporting dashboard
- Deployment

---

## About This Project

KoboTap was built as a portfolio project to demonstrate practical experience with Django, payment integration, REST APIs, backend architecture, authentication, and financial transaction workflows.

The application focuses on clean architecture, secure payment processing, and handling real-world scenarios such as failed provider requests and transaction verification.

---

## License

This project is intended for educational and portfolio purposes.
