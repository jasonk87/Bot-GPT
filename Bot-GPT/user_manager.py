from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash

# This script should be run from the root of the Bot-GPT project.

# Create a minimal Flask app context to interact with the database
app = Flask(__name__)
# Point to the correct database path inside the instance folder
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# --- Database Model (Must match the one in your main app) ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)


# --- Tool Functions ---

def list_users():
    """Prints all users in the database."""
    print("\n--- User List ---")
    users = User.query.all()
    if not users:
        print("No users found.")
    for user in users:
        print(f"ID: {user.id}, Username: {user.username}")
    print("-----------------\n")


def add_user():
    """Adds a new user to the database."""
    print("\n--- Add New User ---")
    username = input("Enter username: ").strip()
    if not username:
        print("Username cannot be empty.")
        return
    if User.query.filter_by(username=username).first():
        print("Error: Username already exists.")
        return

    print("\n[WARNING] Password will be visible as you type.")
    password = input("Enter password: ")
    password_confirm = input("Confirm password: ")

    if password != password_confirm:
        print("Error: Passwords do not match.")
        return

    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    print(f"Successfully added user '{username}'.")
    print("--------------------\n")


def update_password():
    """Updates an existing user's password."""
    print("\n--- Update Password ---")
    username = input("Enter username of the user to update: ").strip()
    user = User.query.filter_by(username=username).first()
    if not user:
        print("Error: User not found.")
        return

    print("\n[WARNING] Password will be visible as you type.")
    password = input("Enter new password: ")
    password_confirm = input("Confirm new password: ")

    if password != password_confirm:
        print("Error: Passwords do not match.")
        return

    user.set_password(password)
    db.session.commit()
    print(f"Successfully updated password for '{username}'.")
    print("-----------------------\n")


def delete_user():
    """Deletes a user from the database."""
    print("\n--- Delete User ---")
    username = input("Enter username of the user to delete: ").strip()
    user = User.query.filter_by(username=username).first()
    if not user:
        print("Error: User not found.")
        return

    confirm = input(
        f"Are you sure you want to delete '{username}'? "
        "This cannot be undone. (y/n): "
    ).lower()
    if confirm == 'y':
        db.session.delete(user)
        db.session.commit()
        print(f"Successfully deleted user '{username}'.")
    else:
        print("Deletion cancelled.")
    print("-------------------\n")


def main_menu():
    """Displays the main menu and handles user input."""
    while True:
        print("\n--- User Management Tool ---")
        print("1. List Users")
        print("2. Add User")
        print("3. Update User Password")
        print("4. Delete User")
        print("5. Exit")
        choice = input("Enter your choice: ")

        if choice == '1':
            list_users()
        elif choice == '2':
            add_user()
        elif choice == '3':
            update_password()
        elif choice == '4':
            delete_user()
        elif choice == '5':
            break
        else:
            print("Invalid choice. Please try again.")


if __name__ == '__main__':
    with app.app_context():
        # Create the database tables if they don't exist
        db.create_all()
        main_menu()
