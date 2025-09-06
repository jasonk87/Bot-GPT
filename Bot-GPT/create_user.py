import argparse
from app import create_app, db
from models import User

def create_user(username, password='password'):
    """Creates a new user with the given username and password."""
    app = create_app()
    with app.app_context():
        if User.query.filter_by(username=username).first() is None:
            print(f"Creating new user '{username}'")
            new_user = User(username=username)
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()
            print("User created.")
        else:
            print(f"User '{username}' already exists.")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a new user for the application.')
    parser.add_argument('username', type=str, help='The username for the new user.')
    parser.add_argument('--password', type=str, default='password', help='The password for the new user.')
    args = parser.parse_args()
    create_user(args.username, args.password)
