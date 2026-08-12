from . import db
from datetime import datetime, timezone, UTC
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import cast, String, Float
from sqlalchemy import DateTime


def _iso_utc(value):
    """Serialize a datetime as canonical ISO-8601 UTC ending in 'Z'.

    Handles both naive values (assumed UTC, as stored) and aware values (the
    model defaults use ``datetime.now(timezone.utc)``) without producing the
    invalid ``...+00:00Z`` that ``isoformat() + 'Z'`` did for aware inputs.
    Returns None for None.
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat() + 'Z'


# --- Association Tables ---
group_compute_server_access = db.Table(
    'group_compute_server_access',
    db.Column('group_id', db.Integer, db.ForeignKey('group.id'), primary_key=True),
    db.Column('compute_server_id', db.Integer, db.ForeignKey('compute_server.id'), primary_key=True)
)


# --- Models ---
class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    image_whitelist = db.Column(db.Text, nullable=True)  # Comma-separated list of image role names

    members = db.relationship('GroupMembership', back_populates='group', cascade="all, delete-orphan")
    projects = db.relationship('Project', foreign_keys='Project.owner_group_id', backref='owner_group', lazy='dynamic')
    shares = db.relationship('ProjectShare', foreign_keys='ProjectShare.user_uid',
                             primaryjoin="ProjectShare.user_uid == 'group:' + cast(Group.id, String)",
                             back_populates='group_share', lazy='dynamic', cascade="all, delete-orphan")

    compute_servers = db.relationship(
        'ComputeServer',
        secondary=group_compute_server_access,
        backref=db.backref('accessible_by_groups', lazy='dynamic'),
        lazy='dynamic'
    )
    gpu_access_rules = db.relationship('GroupGpuAccess', back_populates='group', cascade="all, delete-orphan",
                                       lazy='dynamic')
    cpu_access_rules = db.relationship('GroupCpuLimit', back_populates='group', cascade="all, delete-orphan",
                                       lazy='dynamic')

    def to_dict(self):
        gpu_access_rules = {}
        for rule in self.gpu_access_rules:
            gpu_access_rules[rule.compute_server_id] = rule.allowed_gpus

        cpu_access_rules = {}
        for rule in self.cpu_access_rules:
            cpu_access_rules[rule.compute_server_id] = rule.cpu_limit

        return {
            'id': self.id,
            'name': self.name,
            'image_whitelist': self.image_whitelist.split(',') if self.image_whitelist else [],
            'member_count': len(self.members),
            'accessible_server_ids': [s.id for s in self.compute_servers],
            'gpu_access_rules': gpu_access_rules,
            'cpu_access_rules': cpu_access_rules,
        }


class GroupMembership(db.Model):
    __tablename__ = 'group_membership'
    user_uid = db.Column(db.String(128), primary_key=True)  # "local:<id>" or "ldap:<uid>"
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), primary_key=True)
    is_group_admin = db.Column(db.Boolean, default=False, nullable=False)

    group = db.relationship('Group', back_populates='members')


class GroupGpuAccess(db.Model):
    __tablename__ = 'group_gpu_access'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    compute_server_id = db.Column(db.Integer, db.ForeignKey('compute_server.id'), nullable=False)
    allowed_gpus = db.Column(db.String(255), nullable=False)  # e.g., "0,1,3" or "all"

    group = db.relationship('Group', back_populates='gpu_access_rules')
    compute_server = db.relationship('ComputeServer')
    __table_args__ = (db.UniqueConstraint('group_id', 'compute_server_id', name='_group_server_gpu_uc'),)

    def to_dict(self):
        return {
            'id': self.id,
            'group_id': self.group_id,
            'compute_server_id': self.compute_server_id,
            'allowed_gpus': self.allowed_gpus
        }


class GroupCpuLimit(db.Model):
    __tablename__ = 'group_cpu_limit'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    compute_server_id = db.Column(db.Integer, db.ForeignKey('compute_server.id'), nullable=False)
    cpu_limit = db.Column(db.Float, nullable=True)  # Null means unlimited

    group = db.relationship('Group', back_populates='cpu_access_rules')
    compute_server = db.relationship('ComputeServer')
    __table_args__ = (db.UniqueConstraint('group_id', 'compute_server_id', name='_group_server_cpu_uc'),)

    def to_dict(self):
        return {
            'id': self.id,
            'group_id': self.group_id,
            'compute_server_id': self.compute_server_id,
            'cpu_limit': self.cpu_limit
        }


class LocalUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)  # Increased length for future hash algorithms
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships (optional but can be useful)
    projects = db.relationship('Project',
                               foreign_keys='Project.owner_local_user_id',
                               backref='local_owner',
                               lazy='dynamic')
    containers = db.relationship('ContainerInstance',
                                 foreign_keys='ContainerInstance.user_local_user_id',
                                 backref='local_user',
                                 lazy='dynamic')
    memberships = db.relationship('GroupMembership',
                                  foreign_keys=[GroupMembership.user_uid],
                                  primaryjoin=lambda: GroupMembership.user_uid == 'local:' + cast(LocalUser.id, String),
                                  lazy='dynamic')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_user_identifier(self):
        """Returns the identifier used for ownership links etc."""
        return f"local:{self.id}"

    def to_dict(self, include_email=False):  # Basic dict representation
        from .user_management import get_user_admin_status
        is_admin = get_user_admin_status(self.get_user_identifier())
        data = {
            'id': self.id,
            'username': self.username,
            'is_admin': is_admin,
            'created_at': _iso_utc(self.created_at),
            'user_type': 'local'
        }
        return data


class UserSSHKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    local_user_id = db.Column(db.Integer, db.ForeignKey('local_user.id'), nullable=True)
    user_uid = db.Column(db.String(128), index=True, nullable=True)  # Link to LDAP uid
    name = db.Column(db.String(128), nullable=False)
    public_key = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Add constraint to ensure key name is unique per user
    __table_args__ = (
        db.UniqueConstraint('user_uid', 'name', name='_user_ssh_key_uc'),
        db.CheckConstraint(
            '(user_uid IS NOT NULL AND local_user_id IS NULL) OR (user_uid IS NULL AND local_user_id IS NOT NULL)',
            name='cc_ssh_key_user'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'public_key': self.public_key,  # Be cautious about exposing full public key if not needed
            'created_at': _iso_utc(self.created_at),
        }


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), index=True, nullable=False)

    # --- Ownership Fields (Choose One per Project) ---
    owner_uid = db.Column(db.String(128), index=True, nullable=True)  # Store LDAP uid
    owner_local_user_id = db.Column(db.Integer, db.ForeignKey('local_user.id'), index=True,
                                    nullable=True)  # FK to LocalUser
    owner_group_id = db.Column(db.Integer, db.ForeignKey('group.id'), index=True, nullable=True)
    # --- End Ownership ---

    containers = db.relationship('ContainerInstance', backref='project', lazy='dynamic')
    shares = db.relationship('ProjectShare', back_populates='project', lazy='dynamic', cascade="all, delete-orphan")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Name is unique per owner, not globally: two users may each own a project
    # called "thesis", but one owner can't have two of the same name. A plain
    # composite UNIQUE(name, owner_uid, owner_local_user_id, owner_group_id) would
    # NOT work here: two of the three owner columns are always NULL, and SQL
    # treats NULLs as distinct, so same-owner duplicates would slip through. Use
    # one partial unique index per owner kind instead (works on Postgres+SQLite).
    __table_args__ = (
        db.CheckConstraint(
            '(owner_uid IS NOT NULL AND owner_local_user_id IS NULL AND owner_group_id IS NULL) OR '
            '(owner_uid IS NULL AND owner_local_user_id IS NOT NULL AND owner_group_id IS NULL) OR '
            '(owner_uid IS NULL AND owner_local_user_id IS NULL AND owner_group_id IS NOT NULL)',
            name='cc_project_owner_exclusive'
        ),
        db.Index('uq_project_name_owner_local', 'name', 'owner_local_user_id',
                 unique=True, sqlite_where=db.text('owner_local_user_id IS NOT NULL'),
                 postgresql_where=db.text('owner_local_user_id IS NOT NULL')),
        db.Index('uq_project_name_owner_uid', 'name', 'owner_uid',
                 unique=True, sqlite_where=db.text('owner_uid IS NOT NULL'),
                 postgresql_where=db.text('owner_uid IS NOT NULL')),
        db.Index('uq_project_name_owner_group', 'name', 'owner_group_id',
                 unique=True, sqlite_where=db.text('owner_group_id IS NOT NULL'),
                 postgresql_where=db.text('owner_group_id IS NOT NULL')),
    )

    @hybrid_property
    def owner_identifier(self) -> str:
        if self.owner_local_user_id:
            return f'local:{self.owner_local_user_id}'
        elif self.owner_uid:
            return f'ldap:{self.owner_uid}'
        elif self.owner_group_id:
            return f'group:{self.owner_group_id}'
        return 'error:OwnerUnknown'

    def get_owner_display(self) -> str:
        if self.owner_local_user_id and self.local_owner:
            return f"{self.local_owner.username} (Local)"
        elif self.owner_uid:
            return f"{self.owner_uid} (LDAP)"
        elif self.owner_group_id and self.owner_group:
            return f"{self.owner_group.name} (Group)"
        return "Unknown"

    @property
    def owner_dir_name(self) -> str:
        """
        Returns the directory name segment for the project owner.
        - Local User: returns username (not ID)
        - LDAP User: returns uid
        - Group: returns group name
        """
        if self.owner_local_user_id:
            # Relies on the 'local_owner' backref from LocalUser.projects
            if self.local_owner:
                return self.local_owner.username
            # Fallback in case relationship isn't eager loaded.
            u = db.session.get(LocalUser, self.owner_local_user_id)
            return u.username if u else str(self.owner_local_user_id)

        elif self.owner_group_id:
            # Relies on the 'owner_group' backref from Group.projects
            if self.owner_group:
                return self.owner_group.name
            # Fallback in case relationship isn't eager loaded.
            g = db.session.get(Group, self.owner_group_id)
            return g.name if g else str(self.owner_group_id)

        elif self.owner_uid:
            return self.owner_uid

        return "unknown_owner"

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'owner_display': self.get_owner_display(),  # More informative owner field
            'created_at': _iso_utc(self.created_at),
        }


class ProjectShare(db.Model):
    __tablename__ = 'project_share'
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    user_uid = db.Column(db.String(128), nullable=False, index=True)  # "local:<id>", "ldap:<uid>", or "group:<id>"
    is_writable = db.Column(db.Boolean, default=False, nullable=False)

    project = db.relationship('Project', back_populates='shares')
    group_share = db.relationship('Group',
                                  foreign_keys=[user_uid],
                                  primaryjoin="ProjectShare.user_uid == 'group:' + cast(Group.id, String)",
                                  back_populates='shares', uselist=False)

    __table_args__ = (db.UniqueConstraint('project_id', 'user_uid', name='_project_user_uc'),)

    def to_dict(self):
        return {
            'id': self.id,
            'project_id': self.project_id,
            'user_uid': self.user_uid,
            'is_writable': self.is_writable,
        }


server_static_address_association = db.Table(
    'server_static_address_association',
    db.Column('static_address_id', db.Integer, db.ForeignKey('static_address.id'), primary_key=True),
    db.Column('compute_server_id', db.Integer, db.ForeignKey('compute_server.id'), primary_key=True)
)


class Network(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), unique=True, nullable=False)
    base_ip = db.Column(db.String(45), nullable=False)  # e.g., "192.168.1.0"
    prefix_size = db.Column(db.Integer, nullable=False)  # e.g., 24
    gateway = db.Column(db.String(45), nullable=False)

    # Relationship back to StaticAddress (one-to-many)
    # The 'static_addresses' attribute will be available on Network objects
    static_addresses = db.relationship('StaticAddress', backref='network', lazy='dynamic')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'base_ip': self.base_ip,
            'prefix_size': self.prefix_size,
            'gateway': self.gateway,
        }


class StaticAddress(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Use specific PG types if possible, fallback to String w/ validation otherwise
    # ip_address = db.Column(INET, unique=True, index=True, nullable=False) # PG specific
    # mac_address = db.Column(MACADDR, unique=True, index=True, nullable=False) # PG specific
    ip_address = db.Column(db.String(45), unique=True, index=True, nullable=False)  # IPv4/IPv6 fallback
    mac_address = db.Column(db.String(17), unique=True, index=True, nullable=False)  # Standard MAC format fallback
    comment = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    network_id = db.Column(db.Integer, db.ForeignKey('network.id'), nullable=False)

    # Many-to-Many relationship with ComputeServer
    available_servers = db.relationship(
        'ComputeServer',
        secondary=server_static_address_association,
        back_populates='available_addresses',  # Use back_populates for bidirectional relationship
    )

    # Relationship back to the container currently assigned (if any)
    # This assumes the FK 'static_address_id' is on ContainerInstance
    assigned_container = db.relationship(
        'ContainerInstance',
        back_populates='static_address',
        uselist=False,  # One-to-one from address perspective
        foreign_keys='ContainerInstance.static_address_id'
    )

    def to_dict(self, include_servers=False):
        data = {
            'id': self.id,
            'ip_address': str(self.ip_address),  # Cast IP/MAC types to string if needed
            'mac_address': str(self.mac_address),
            'network_id': self.network_id,
            'network_name': self.network.name,
            'comment': self.comment,
            'created_at': _iso_utc(self.created_at),
            'assigned_container_id': self.assigned_container.id if self.assigned_container else None,
            'assigned_container_user': self.assigned_container.get_user_display() if self.assigned_container else None,
        }
        if include_servers:
            # Eagerly load servers or handle dynamic loading carefully
            data['available_server_ids'] = [s.id for s in self.available_servers]
        return data


class ComputeServer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    hostname = db.Column(db.String(64), index=True, unique=True, nullable=False)
    ssh_port = db.Column(db.Integer, nullable=False, default=22)
    gpu_count = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    containers = db.relationship('ContainerInstance', backref='compute_server', lazy='dynamic')
    # Many-to-Many relationship with StaticAddress
    available_addresses = db.relationship(
        'StaticAddress',
        secondary=server_static_address_association,
        back_populates='available_servers',  # Link back
    )

    def to_dict(self):
        return {'id': self.id, 'hostname': self.hostname, 'ssh_port': self.ssh_port, 'gpu_count': self.gpu_count}


class ContainerInstance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # --- User/Owner Fields (Choose One per Container) ---
    user_uid = db.Column(db.String(128), index=True, nullable=True)  # LDAP uid of the user who started it
    user_local_user_id = db.Column(db.Integer, db.ForeignKey('local_user.id'), index=True,
                                   nullable=True)  # FK to LocalUser
    # --- End User/Owner ---
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    compute_server_id = db.Column(db.Integer, db.ForeignKey('compute_server.id'), nullable=False)
    image_name = db.Column(db.String(128), nullable=False)
    ssh_key_id = db.Column(db.Integer, db.ForeignKey('user_ssh_key.id'), nullable=True)
    gpus = db.Column(db.String(64), nullable=False)
    cpu_limit = db.Column(db.Float, nullable=True)  # New CPU limit definition
    status = db.Column(db.String(32), index=True, default='PENDING', nullable=False)
    created_at = db.Column(db.DateTime, index=True, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))
    container_name = db.Column(db.String(255), nullable=True)
    ssh_key = db.relationship('UserSSHKey')
    directory_path = db.Column(db.String(512), nullable=True)
    static_address_id = db.Column(db.Integer, db.ForeignKey('static_address.id'), nullable=True, unique=True)
    static_address = db.relationship(
        'StaticAddress',
        back_populates='assigned_container',
        foreign_keys=[static_address_id]
    )
    ttl_date = db.Column(db.DateTime(timezone=True), nullable=True)
    ansible_jobs = db.relationship('AnsibleJob', back_populates='container', lazy='dynamic',
                                   cascade="all, delete-orphan",
                                   order_by=lambda: AnsibleJob.created_at.desc())

    # Add constraint to ensure one user type is set
    __table_args__ = (
        db.CheckConstraint(
            '(user_uid IS NOT NULL AND user_local_user_id IS NULL) OR (user_uid IS NULL AND user_local_user_id IS NOT NULL)',
            name='cc_container_user'),
    )

    @hybrid_property
    def user(self):
        """
        A hybrid property to return a unified user object (wrapper),
        regardless of whether it's a LocalUser or an LDAP user.
        This allows consistent access like `container.user.username` or
        `container.user.get_ansible_user_params()` even in background jobs.
        """
        # To avoid circular import errors, wrappers are imported here.
        from .user_management import LdapUserWrapper, LocalUserWrapper
        from .services import ldap_service

        if self.user_local_user_id and self.local_user:
            # For local DB users, wrap the SQLAlchemy object.
            return LocalUserWrapper(self.local_user)
        elif self.user_uid:
            # For LDAP users, we must re-fetch details from LDAP since
            # the background Ansible job does not have session context.
            ldap_details = ldap_service.get_ldap_user_details(self.user_uid)
            if ldap_details:
                return LdapUserWrapper(ldap_details)
            # If details can't be fetched, something is wrong (e.g., LDAP server down).
            # Returning None will cause the Ansible job to fail, which is correct.
            from flask import current_app
            current_app.logger.error(f"Failed to get LDAP details for UID '{self.user_uid}' for container {self.id}")
            return None
        return None

    def get_user_display(self):
        if self.user_local_user_id and self.local_user:
            return f"{self.local_user.username} (Local)"
        elif self.user_uid:
            # Check if user_uid follows the "local:id" pattern (e.g., if linked via SSH key only)
            if self.user_uid.startswith("local:"):
                try:
                    local_id = int(self.user_uid.split(":")[1])
                    # Avoid direct query here if possible, rely on relationship or pass user object
                    # For simplicity now, just display the ID
                    return f"local:{local_id} (Local)"
                except (ValueError, IndexError):
                    return f"{self.user_uid} (Unknown format)"
            return f"{self.user_uid} (LDAP)"
        return "Unknown"

    def to_dict(self):
        ip = self.static_address.ip_address if self.static_address else None
        mac = self.static_address.mac_address if self.static_address else None
        latest_job = self.ansible_jobs.first()
        return {
            'id': self.id,
            'user_display': self.get_user_display(),  # More informative user field
            'username': self.user.username if self.user else 'Unknown',
            'project': self.project.name if self.project else None,
            'server': self.compute_server.hostname if self.compute_server else None,
            'server_ssh_port': self.compute_server.ssh_port if self.compute_server else 22,
            'image': self.image_name,
            'container_name': self.container_name,
            'ssh_key_name': self.ssh_key.name if self.ssh_key else None,
            'directory_path': self.directory_path,
            'gpus': self.gpus,
            'cpu_limit': self.cpu_limit,
            'status': self.status,
            'ip_address': str(ip) if ip else None,
            'mac_address': str(mac) if mac else None,
            'created_at': _iso_utc(self.created_at),
            'updated_at': _iso_utc(self.updated_at),
            'ttl_date': self.ttl_date.isoformat() if self.ttl_date else None,
            'ansible_log': latest_job.log if latest_job else None
        }


class LdapUserCache(db.Model):
    __tablename__ = 'ldap_user_cache'
    uid = db.Column(db.String(128), primary_key=True)
    full_name = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(255), nullable=True)
    cached_at = db.Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))


class AnsibleJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    container_instance_id = db.Column(db.Integer, db.ForeignKey('container_instance.id'), nullable=False)
    server_id = db.Column(db.Integer, db.ForeignKey('compute_server.id'), nullable=False)
    status = db.Column(db.String(32), default='PENDING', nullable=False)
    action = db.Column(db.String(32), nullable=False, index=True, server_default='create')
    log = db.Column(db.Text, default='', nullable=False)
    playbook = db.Column(db.Text, default='', nullable=False)
    extravars = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(UTC))

    container = db.relationship('ContainerInstance', back_populates='ansible_jobs')
    server = db.relationship('ComputeServer')

    def to_dict(self):
        return {
            'id': self.id,
            'container_id': self.container_instance_id,
            'status': self.status,
            'action': self.action
        }


class FileOperationJob(db.Model):
    __tablename__ = 'file_operation_job'
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(32), default='PENDING', nullable=False, index=True)
    operation = db.Column(db.String(64), nullable=False, index=True)
    payload = db.Column(db.Text, nullable=False)  # JSON string with operation arguments
    log = db.Column(db.Text, default='', nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            'id': self.id,
            'status': self.status,
            'operation': self.operation,
            'log': self.log,
            'created_at': _iso_utc(self.created_at),
            'updated_at': _iso_utc(self.updated_at),
        }
