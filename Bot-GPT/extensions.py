from flask_socketio import SocketIO

# Remove db and login_manager as they will be re-initialized in app.py
socketio = SocketIO()
