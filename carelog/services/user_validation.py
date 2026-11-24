from psycopg import Cursor

from carelog.database.repositories.select_user import select_user


# The roles of the users table (CHECK constraint chk_users_role)
ALLOWED_ROLES = ("admin", "worker")


def validate_user_id(user_id: int) -> None:

    # bool is a subclass of int in Python, so type() is used instead of
    # isinstance(): True would otherwise be accepted as user 1.

    if type(user_id) is not int:
        raise ValueError("User ID must be an integer")

    if user_id <= 0:
        raise ValueError("User ID must be positive")


def get_active_user(cursor: Cursor, actor_user_id: int) -> dict:

    # Checks the user who performs the action and returns
    # {"id", "role", "is_active"}. The role is always read from the
    # database, never taken from the caller.
    #
    # Use the cursor of the service's own transaction, so the check and
    # the writes after it are rolled back together on an error.

    validate_user_id(actor_user_id)

    user = select_user(cursor, actor_user_id)

    if user is None:
        raise ValueError("User not found")

    if not user["is_active"]:
        raise PermissionError("User is not active")

    if user["role"] not in ALLOWED_ROLES:
        raise PermissionError("User role is not allowed")

    return user


def is_admin(user: dict) -> bool:

    # user must come from get_active_user()

    return user["role"] == "admin"


def check_worker_access(actor: dict, owner_user_id: int) -> None:

    # Raises PermissionError unless the actor may handle, or create, a
    # record that belongs to the worker owner_user_id: a worker only their
    # own records, an admin the records of every worker.
    #
    # actor must come from get_active_user().

    validate_user_id(owner_user_id)

    if is_admin(actor):
        return

    if actor["id"] == owner_user_id:
        return

    raise PermissionError("User cannot handle another worker's records")


def get_owner_filter(actor: dict, user_id: int | None) -> int | None:

    # Returns the worker whose records a search is limited to in SQL:
    # - user_id given: that worker. A worker may give only their own ID.
    # - no user_id: an admin gets None, which means every worker, and a
    #   worker gets their own ID.
    #
    # actor must come from get_active_user().

    if user_id is not None:
        check_worker_access(actor, user_id)
        return user_id

    if is_admin(actor):
        return None

    return actor["id"]


def resolve_owner_id(cursor: Cursor, actor: dict, user_id: int | None) -> int:

    # Returns the worker who owns a new record, for example a visit or an
    # expense. Without user_id the actor is the owner. Only an admin may
    # choose another worker, who must be an existing, active user. The
    # actor is not read from the database a second time.
    #
    # actor must come from get_active_user().

    if user_id is None or user_id == actor["id"]:
        return actor["id"]

    check_worker_access(actor, user_id)
    get_active_user(cursor, user_id)

    return user_id
