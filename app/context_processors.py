from app.extensions import db
from app.models import Settings


def inject_server_name():
    from sqlalchemy.exc import OperationalError, PendingRollbackError

    try:
        # Use no_autoflush to prevent triggering pending session changes
        with db.session.no_autoflush:
            setting = Settings.query.filter_by(key="server_name").first()
            # Handle None, empty string, or missing setting gracefully
            server_name = setting.value if setting and setting.value else "Wizarr"
    except (OperationalError, PendingRollbackError) as e:
        if "database is locked" in str(e).lower():
            # Fallback to default if database is locked
            server_name = "Wizarr"
        else:
            raise
    except Exception:
        # Fallback to default for any other database errors
        server_name = "Wizarr"

    return {"server_name": server_name}
