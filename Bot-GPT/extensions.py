try:
    from flask_socketio import SocketIO
except ImportError:  # pragma: no cover - exercised only in minimal environments
    class SocketIO:  # type: ignore[override]
        """Small fallback used when flask_socketio is unavailable."""

        def init_app(self, app, **kwargs):
            app.logger.warning(
                "flask_socketio is not installed; running without realtime socket support."
            )

        def on(self, _event_name):
            def decorator(func):
                return func

            return decorator

        def emit(self, *args, **kwargs):
            return None

        def run(self, app, **kwargs):
            app.run(
                host=kwargs.get("host"),
                port=kwargs.get("port"),
                debug=kwargs.get("debug", False),
                use_reloader=kwargs.get("use_reloader", False),
            )

socketio = SocketIO()
