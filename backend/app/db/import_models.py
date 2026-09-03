"""Ensures every ORM model module is imported before any cross-module
relationship needs to resolve.

``Sprint.tickets`` (in ``modules/sprints/models.py``) references
``"Ticket"`` (defined in ``modules/tickets/models.py``) by string name to
avoid a circular import between the two modules. SQLAlchemy resolves
that string lazily, the first time the relationship is actually used —
but it can only resolve to a class that has already been imported
somewhere and registered on ``Base``'s mapper registry. If request
ordering happened to trigger that resolution before ``tickets/models.py``
was ever imported by anything else, it would fail — not because of a
real bug, but because of which route happened to run first.

Importing this module once, early — from ``Alembic``'s ``env.py`` and
from the application's startup path — makes model registration
deterministic instead of dependent on request order.
"""

from __future__ import annotations

from app.modules.auth import models as _auth_models  # noqa: F401
from app.modules.sprints import models as _sprints_models  # noqa: F401
from app.modules.tickets import models as _tickets_models  # noqa: F401
from app.modules.audit import models as _audit_models  # noqa: F401
