"""Import mọi model SQLModel ở đây để Alembic (migrations/env.py) thấy bảng."""

import app.auth.models  # noqa: E402, F401 — users, oauth_accounts, refresh_tokens, permissions, roles, role_permissions, user_roles
import app.tenants.models  # noqa: F401 — tenants (trước users: FK users.tenant_id)
from app.agent.chat.models import AgentApproval, AgentMessage, AgentRun, AgentSession  # noqa: F401
from app.agent.config.models import Agent, AgentProvider  # noqa: F401
from app.agent.guard.models import AgentChatBlock  # noqa: F401
from app.agent.router.models import OrchestratorRoute  # noqa: F401
from app.credentials.models import Credential  # noqa: F401
from app.notifications.models import Notification  # noqa: F401
from app.system.models import SystemSettingsRow  # noqa: F401
from app.tasks.models import Task, TaskComment  # noqa: F401
