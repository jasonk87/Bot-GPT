from app import create_app, db
from models import User

app = create_app()

with app.app_context():
    # Check if user already exists
    if User.query.filter_by(username='testuser').first() is None:
        print("Creating new user 'testuser'")
        new_user = User(username='testuser')
        new_user.set_password('password')
        db.session.add(new_user)
        db.session.commit()
        print("User created.")
    else:
        print("User 'testuser' already exists.")
