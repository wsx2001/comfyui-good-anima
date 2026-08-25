"""Schema migration helpers.

M0 uses ``SQLModel.metadata.create_all`` (in ``db.init_db``) which is
idempotent and adds new tables without altering existing ones. As long
as the schema only ever *grows*, that's enough.

When M1 introduces real tables with constraints, we'll switch to
Alembic. For now this module is a placeholder documenting the policy.
"""