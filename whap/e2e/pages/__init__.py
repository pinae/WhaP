"""Page objects: what a person sees and does in WhaP, addressed by data-testid.

Tests read as user actions ("add an SSH key") and never touch selectors; when
the frontend changes, only this package does. Methods wait for the visible
outcome a person would wait for, not for network requests.
"""
from .login import LoginPage
from .user_panel import UserPanel

__all__ = ["LoginPage", "UserPanel"]
