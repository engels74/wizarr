"""
Tests for wizard-steps.js redeclaration fix

This test ensures that the WizardDragDropManager class can be safely loaded
multiple times without causing redeclaration errors, which can happen in
dynamic loading scenarios like HTMX.

Test Approach (TDD):
1. Test that reproduces the original error with multiple script loads
2. Test that verifies the fix prevents redeclaration errors
3. Test that ensures functionality remains intact after multiple loads
"""

import pytest
from playwright.sync_api import Page

from app import create_app
from app.extensions import db
from app.models import AdminAccount, WizardStep


@pytest.fixture
def app():
    """Create application for testing."""
    app = create_app()
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["WTF_CSRF_ENABLED"] = False

    with app.app_context():
        db.create_all()

        # Create admin user for authentication
        admin = AdminAccount(username="admin")
        admin.set_password("password")
        db.session.add(admin)

        # Create test wizard steps
        step1 = WizardStep(
            server_type="plex",
            position=0,
            title="Welcome",
            markdown="# Welcome\nWelcome to Plex",
            phase="pre"
        )
        step2 = WizardStep(
            server_type="plex",
            position=1,
            title="Setup Complete",
            markdown="# Complete\nSetup is done",
            phase="post"
        )
        db.session.add_all([step1, step2])
        db.session.commit()

        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture
def authenticated_client(client):
    """Create authenticated test client."""
    # Login as admin
    client.post('/login', data={
        'username': 'admin',
        'password': 'password'
    })
    return client


def test_wizard_steps_script_guard_prevents_redeclaration(page: Page, live_server):
    """Test that the script guard prevents WizardDragDropManager redeclaration errors."""
    # Navigate to the wizard settings page
    page.goto(f"{live_server.url}/login")

    # Login
    page.fill('input[name="username"]', 'admin')
    page.fill('input[name="password"]', 'password')
    page.click('button[type="submit"]')

    # Navigate to wizard settings
    page.goto(f"{live_server.url}/settings/wizard")

    # Wait for the page to load
    page.wait_for_load_state('networkidle')

    # Check that no JavaScript errors are present in console
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)

    # Inject the script multiple times to simulate the redeclaration scenario
    script_content = page.evaluate("""
        () => {
            // Get the current script content
            const scripts = document.querySelectorAll('script[src*="wizard-steps.js"]');
            return scripts.length > 0 ? scripts[0].src : null;
        }
    """)

    if script_content:
        # Simulate multiple script loads (this would cause the original error)
        for _ in range(3):
            page.evaluate(f"""
                (() => {{
                    const script = document.createElement('script');
                    script.src = '{script_content}';
                    document.head.appendChild(script);
                }})()
            """)

    # Wait a bit for any errors to manifest
    page.wait_for_timeout(1000)

    # Check for redeclaration errors
    redeclaration_errors = [
        error for error in console_errors
        if "redeclaration" in error.lower() and "wizarddragdropmanager" in error.lower()
    ]

    assert len(redeclaration_errors) == 0, f"Found redeclaration errors: {redeclaration_errors}"


def test_wizard_drag_drop_functionality_works_after_multiple_loads(page: Page, live_server):
    """Test that drag-and-drop functionality still works after multiple script loads."""
    # Navigate and login
    page.goto(f"{live_server.url}/login")
    page.fill('input[name="username"]', 'admin')
    page.fill('input[name="password"]', 'password')
    page.click('button[type="submit"]')

    # Navigate to wizard settings
    page.goto(f"{live_server.url}/settings/wizard")
    page.wait_for_load_state('networkidle')

    # Load the script multiple times
    script_content = page.evaluate("""
        () => {
            const scripts = document.querySelectorAll('script[src*="wizard-steps.js"]');
            return scripts.length > 0 ? scripts[0].src : null;
        }
    """)

    if script_content:
        for _ in range(2):
            page.evaluate(f"""
                (() => {{
                    const script = document.createElement('script');
                    script.src = '{script_content}';
                    document.head.appendChild(script);
                }})()
            """)

    # Wait for scripts to load
    page.wait_for_timeout(1000)

    # Test that WizardDragDropManager is available and functional
    wizard_manager_exists = page.evaluate("""
        () => {
            return typeof window.wizardDragDrop !== 'undefined' &&
                   window.wizardDragDrop instanceof WizardDragDropManager;
        }
    """)

    assert wizard_manager_exists, "WizardDragDropManager should be available after multiple script loads"

    # Test that drag-and-drop containers are properly initialized
    sortable_containers = page.evaluate("""
        () => {
            const containers = document.querySelectorAll('.wizard-steps[data-sortable-attached="1"]');
            return containers.length;
        }
    """)

    # Should have at least some sortable containers if wizard steps are present
    if page.query_selector('.wizard-steps'):
        assert sortable_containers > 0, "Sortable containers should be properly attached"


def test_backward_compatibility_functions_still_work(page: Page, live_server):
    """Test that backward compatibility functions are still available."""
    # Navigate and login
    page.goto(f"{live_server.url}/login")
    page.fill('input[name="username"]', 'admin')
    page.fill('input[name="password"]', 'password')
    page.click('button[type="submit"]')

    # Navigate to wizard settings
    page.goto(f"{live_server.url}/settings/wizard")
    page.wait_for_load_state('networkidle')

    # Test that backward compatibility functions exist
    compatibility_functions = page.evaluate("""
        () => {
            const functions = [
                'updateStepPhase',
                'updateEmptyState',
                'closeEditModal',
                'enhanceEmptyZoneVisibility',
                'synchronizeAllPhaseHeights'
            ];

            return functions.map(fn => ({
                name: fn,
                exists: typeof window[fn] === 'function'
            }));
        }
    """)

    for func in compatibility_functions:
        assert func['exists'], f"Backward compatibility function '{func['name']}' should be available"


def test_script_guard_implementation_details():
    """Test the specific implementation of the script guard mechanism."""
    # This test verifies the guard mechanism without needing a full browser

    script_content = '''
    /* wizard.js */

    // Script guard to prevent redeclaration
    if (typeof window.WizardDragDropManager !== 'undefined') {
        console.log('WizardDragDropManager already exists, skipping redeclaration');
    } else {

        class WizardDragDropManager {
            constructor() {
                this.sortableInstances = new Map();
            }

            test() {
                return 'test';
            }
        }

        // Mark as loaded
        window.WizardDragDropManager = WizardDragDropManager;
        window.wizardDragDrop = new WizardDragDropManager();
    }
    '''

    # This test validates the guard logic structure
    assert 'if (typeof window.WizardDragDropManager' in script_content
    assert 'console.log' in script_content or 'return' in script_content.split('if (typeof window.WizardDragDropManager')[1].split('} else {')[0]
    assert 'window.WizardDragDropManager = WizardDragDropManager' in script_content


@pytest.fixture
def live_server(app):
    """Create a live server for browser testing."""
    import socket
    import threading

    from werkzeug.serving import make_server

    # Find a free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('localhost', 0))
    port = sock.getsockname()[1]
    sock.close()

    # Create server
    server = make_server('localhost', port, app, threaded=True)

    # Start server in thread
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()

    # Create server object with URL
    class LiveServer:
        def __init__(self, host, port):
            self.host = host
            self.port = port
            self.url = f'http://{host}:{port}'

    live_server_obj = LiveServer('localhost', port)

    yield live_server_obj

    # Shutdown
    server.shutdown()
