from flask import Blueprint
from .projects import proj_bp
from .permissions import perm_bp
from .groups import grp_bp
from .addresses import sadr_bp
from .sshkeys import sshk_bp
from .servers import srv_bp
from .containers import cont_bp
from .users import user_bp
from .networks import ntwrk_bp
from .stats import stat_bp
from .docs import docs_bp

bp = Blueprint('api', __name__)
bp.register_blueprint(proj_bp)
bp.register_blueprint(perm_bp)
bp.register_blueprint(grp_bp)
bp.register_blueprint(sadr_bp)
bp.register_blueprint(sshk_bp)
bp.register_blueprint(srv_bp)
bp.register_blueprint(cont_bp)
bp.register_blueprint(user_bp)
bp.register_blueprint(ntwrk_bp)
bp.register_blueprint(stat_bp)
bp.register_blueprint(docs_bp)
