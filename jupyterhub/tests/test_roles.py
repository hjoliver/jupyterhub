"""Test roles"""
# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.
import json

from pytest import mark

from .. import orm
from .. import roles
from ..utils import maybe_future
from .mocking import MockHub
from .utils import add_user
from .utils import api_request


@mark.role
def test_orm_roles(db):
    """Test orm roles setup"""
    user_role = orm.Role.find(db, name='user')
    if not user_role:
        user_role = orm.Role(name='user', scopes=['all', 'read:all'])
        db.add(user_role)
        db.commit()

    service_role = orm.Role(name='service', scopes=['users:servers'])
    db.add(service_role)
    db.commit()

    group_role = orm.Role(name='group', scopes=['read:users'])
    db.add(group_role)
    db.commit()

    user = orm.User(name='falafel')
    db.add(user)
    db.commit()

    service = orm.Service(name='kebab')
    db.add(service)
    db.commit()

    group = orm.Group(name='fast-food')
    db.add(group)
    db.commit()

    assert user_role.users == []
    assert user_role.services == []
    assert user_role.groups == []
    assert service_role.users == []
    assert service_role.services == []
    assert service_role.groups == []
    assert user.roles == []
    assert service.roles == []
    assert group.roles == []

    user_role.users.append(user)
    service_role.services.append(service)
    group_role.groups.append(group)
    db.commit()
    assert user_role.users == [user]
    assert user.roles == [user_role]
    assert service_role.services == [service]
    assert service.roles == [service_role]
    assert group_role.groups == [group]
    assert group.roles == [group_role]

    # check token creation without specifying its role
    # assigns it the default 'user' role
    token = user.new_api_token()
    user_token = orm.APIToken.find(db, token=token)
    assert user_token in user_role.tokens
    assert user_role in user_token.roles

    # check creating token with a specific role
    token = service.new_api_token(roles=['service'])
    service_token = orm.APIToken.find(db, token=token)
    assert service_token in service_role.tokens
    assert service_role in service_token.roles

    # check deleting user removes the user and the token from roles
    db.delete(user)
    db.commit()
    assert user_role.users == []
    assert user_token not in user_role.tokens
    # check deleting the service token removes it from service_role
    db.delete(service_token)
    db.commit()
    assert service_token not in service_role.tokens
    # check deleting the service_role removes it from service.roles
    db.delete(service_role)
    db.commit()
    assert service.roles == []
    # check deleting the group removes it from group_roles
    db.delete(group)
    db.commit()
    assert group_role.groups == []

    # clean up db
    db.delete(service)
    db.delete(group_role)
    db.commit()


@mark.role
def test_orm_roles_delete_cascade(db):
    """Orm roles cascade"""
    user1 = orm.User(name='user1')
    user2 = orm.User(name='user2')
    role1 = orm.Role(name='role1')
    role2 = orm.Role(name='role2')
    db.add(user1)
    db.add(user2)
    db.add(role1)
    db.add(role2)
    db.commit()
    # add user to role via user.roles
    user1.roles.append(role1)
    db.commit()
    assert user1 in role1.users
    assert role1 in user1.roles

    # add user to role via roles.users
    role1.users.append(user2)
    db.commit()
    assert user2 in role1.users
    assert role1 in user2.roles

    # fill role2 and check role1 again
    role2.users.append(user1)
    role2.users.append(user2)
    db.commit()
    assert user1 in role1.users
    assert user2 in role1.users
    assert user1 in role2.users
    assert user2 in role2.users
    assert role1 in user1.roles
    assert role1 in user2.roles
    assert role2 in user1.roles
    assert role2 in user2.roles

    # now start deleting
    # 1. remove role via user.roles
    user1.roles.remove(role2)
    db.commit()
    assert user1 not in role2.users
    assert role2 not in user1.roles

    # 2. remove user via role.users
    role1.users.remove(user2)
    db.commit()
    assert user2 not in role1.users
    assert role1 not in user2.roles

    # 3. delete role object
    db.delete(role2)
    db.commit()
    assert role2 not in user1.roles
    assert role2 not in user2.roles

    # 4. delete user object
    db.delete(user1)
    db.delete(user2)
    db.commit()
    assert user1 not in role1.users


@mark.role
@mark.parametrize(
    "scopes, subscopes",
    [
        (
            ['users'],
            {
                'users',
                'read:users',
                'users:activity',
                'users:servers',
                'read:users:name',
                'read:users:groups',
                'read:users:activity',
                'read:users:servers',
            },
        ),
        (
            ['read:users'],
            {
                'read:users',
                'read:users:name',
                'read:users:groups',
                'read:users:activity',
                'read:users:servers',
            },
        ),
        (['read:users:servers'], {'read:users:servers'}),
        (['admin:groups'], {'admin:groups'}),
    ],
)
def test_get_subscopes(db, scopes, subscopes):
    """Test role scopes expansion into their subscopes"""
    roles.add_role(db, {'name': 'testing_scopes', 'scopes': scopes})
    role = orm.Role.find(db, name='testing_scopes')
    response = roles.get_subscopes(role)
    assert response == subscopes
    db.delete(role)


async def test_load_default_roles(tmpdir, request):
    """Test loading default roles in app.py"""
    kwargs = {}
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    await hub.init_roles()
    # test default roles loaded to database
    assert orm.Role.find(db, 'user') is not None
    assert orm.Role.find(db, 'admin') is not None
    assert orm.Role.find(db, 'server') is not None


@mark.role
async def test_load_roles_users(tmpdir, request):
    """Test loading predefined roles for users in app.py"""
    roles_to_load = [
        {
            'name': 'teacher',
            'description': 'Access users information, servers and groups without create/delete privileges',
            'scopes': ['users', 'groups'],
            'users': ['cyclops', 'gandalf'],
        },
        {
            'name': 'user',
            'description': 'Only read access',
            'scopes': ['read:all'],
            'users': ['bilbo'],
        },
    ]
    kwargs = {'load_roles': roles_to_load}
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    hub.authenticator.admin_users = ['admin']
    hub.authenticator.allowed_users = ['cyclops', 'gandalf', 'bilbo', 'gargamel']
    await hub.init_users()
    await hub.init_roles()

    # test if the 'user' role has been overwritten and assigned
    user_role = orm.Role.find(db, 'user')
    admin_role = orm.Role.find(db, 'admin')
    assert user_role is not None
    assert user_role.scopes == ['read:all']

    # test if every user has a role (and no duplicates)
    # and admins have admin role
    for user in db.query(orm.User):
        assert len(user.roles) > 0
        assert len(user.roles) == len(set(user.roles))
        if user.admin:
            assert admin_role in user.roles
            assert user_role not in user.roles

    # test if predefined roles loaded and assigned
    teacher_role = orm.Role.find(db, name='teacher')
    assert teacher_role is not None
    gandalf_user = orm.User.find(db, name='gandalf')
    assert teacher_role in gandalf_user.roles
    cyclops_user = orm.User.find(db, name='cyclops')
    assert teacher_role in cyclops_user.roles


@mark.role
async def test_load_roles_services(tmpdir, request):
    services = [
        {'name': 'cull_idle', 'api_token': 'some-token'},
        {'name': 'user_service', 'api_token': 'some-other-token'},
        {'name': 'admin_service', 'api_token': 'secret-token'},
    ]
    service_tokens = {
        'some-token': 'cull_idle',
        'some-other-token': 'user_service',
        'secret-token': 'admin_service',
    }
    roles_to_load = [
        {
            'name': 'culler',
            'description': 'Cull idle servers',
            'scopes': ['users:servers', 'admin:servers'],
            'services': ['cull_idle'],
        },
    ]
    kwargs = {
        'load_roles': roles_to_load,
        'services': services,
        'service_tokens': service_tokens,
    }
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    await hub.init_api_tokens()
    # make 'admin_service' admin
    admin_service = orm.Service.find(db, 'admin_service')
    admin_service.admin = True
    db.commit()
    await hub.init_roles()

    # test if every service has a role (and no duplicates)
    admin_role = orm.Role.find(db, name='admin')
    user_role = orm.Role.find(db, name='user')
    for service in db.query(orm.Service):
        assert len(service.roles) > 0
        assert len(service.roles) == len(set(service.roles))
        if service.admin:
            assert admin_role in service.roles
            assert user_role not in service.roles

    # test if predefined roles loaded and assigned
    culler_role = orm.Role.find(db, name='culler')
    cull_idle = orm.Service.find(db, name='cull_idle')
    assert culler_role in cull_idle.roles
    assert user_role not in cull_idle.roles

    # delete the test services
    for service in db.query(orm.Service):
        db.delete(service)
    db.commit()

    # delete the test tokens
    for token in db.query(orm.APIToken):
        db.delete(token)
    db.commit()


@mark.role
async def test_load_roles_groups(tmpdir, request):
    """Test loading predefined roles for groups in app.py"""
    groups_to_load = {
        'group1': ['gandalf'],
        'group2': ['bilbo', 'gargamel'],
        'group3': ['cyclops'],
    }
    roles_to_load = [
        {
            'name': 'assistant',
            'description': 'Access users information only',
            'scopes': ['read:users'],
            'groups': ['group2'],
        },
        {
            'name': 'head',
            'description': 'Whole user access',
            'scopes': ['users', 'admin:users'],
            'groups': ['group3'],
        },
    ]
    kwargs = {'load_groups': groups_to_load, 'load_roles': roles_to_load}
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    await hub.init_groups()
    await hub.init_roles()

    assist_role = orm.Role.find(db, name='assistant')
    head_role = orm.Role.find(db, name='head')

    group1 = orm.Group.find(db, name='group1')
    group2 = orm.Group.find(db, name='group2')
    group3 = orm.Group.find(db, name='group3')

    # test group roles
    assert group1.roles == []
    assert group2 in assist_role.groups
    assert group3 in head_role.groups


@mark.role
async def test_load_roles_user_tokens(tmpdir, request):
    user_tokens = {
        'secret-token': 'cyclops',
        'secrety-token': 'gandalf',
        'super-secret-token': 'admin',
    }
    roles_to_load = [
        {
            'name': 'reader',
            'description': 'Read-only own model',
            'scopes': ['read:all'],
            'tokens': ['secrety-token'],
        },
    ]
    kwargs = {
        'load_roles': roles_to_load,
        'api_tokens': user_tokens,
    }
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    hub.authenticator.admin_users = ['admin']
    hub.authenticator.allowed_users = ['cyclops', 'gandalf']
    await hub.init_users()
    await hub.init_api_tokens()
    await hub.init_roles()

    # test if gandalf's token has the 'reader' role
    reader_role = orm.Role.find(db, 'reader')
    token = orm.APIToken.find(db, 'secrety-token')
    assert reader_role in token.roles

    # test if all other tokens have default 'user' role
    user_role = orm.Role.find(db, 'user')
    sec_token = orm.APIToken.find(db, 'secret-token')
    assert user_role in sec_token.roles
    s_sec_token = orm.APIToken.find(db, 'super-secret-token')
    assert user_role in s_sec_token.roles

    # delete the test tokens
    for token in db.query(orm.APIToken):
        db.delete(token)
    db.commit()


@mark.role
async def test_load_roles_user_tokens_not_allowed(tmpdir, request):
    user_tokens = {
        'secret-token': 'bilbo',
    }
    roles_to_load = [
        {
            'name': 'user-reader',
            'description': 'Read-only any user model',
            'scopes': ['read:users'],
            'tokens': ['secret-token'],
        },
    ]
    kwargs = {
        'load_roles': roles_to_load,
        'api_tokens': user_tokens,
    }
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    hub.authenticator.allowed_users = ['bilbo']
    await hub.init_users()
    await hub.init_api_tokens()

    response = 'allowed'
    # bilbo has only default 'user' role
    # while bilbo's token is requesting role with higher permissions
    try:
        await hub.init_roles()
    except ValueError:
        response = 'denied'

    assert response == 'denied'

    # delete the test tokens
    for token in db.query(orm.APIToken):
        db.delete(token)
    db.commit()


@mark.role
async def test_load_roles_service_tokens(tmpdir, request):
    services = [{'name': 'cull_idle', 'api_token': 'another-secret-token'}]
    service_tokens = {
        'another-secret-token': 'cull_idle',
    }
    roles_to_load = [
        {
            'name': 'culler',
            'description': 'Cull idle servers',
            'scopes': ['users:servers', 'admin:users:servers'],
            'tokens': ['another-secret-token'],
        },
    ]
    kwargs = {
        'load_roles': roles_to_load,
        'services': services,
        'service_tokens': service_tokens,
    }
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    await hub.init_api_tokens()
    # make the service admin
    service = orm.Service.find(db, 'cull_idle')
    service.admin = True
    await hub.init_roles()

    # test if another-secret-token has culler role
    culler_role = orm.Role.find(db, 'culler')
    token = orm.APIToken.find(db, 'another-secret-token')
    assert len(token.roles) == 1
    assert culler_role in token.roles

    # delete the test services
    for service in db.query(orm.Service):
        db.delete(service)
    db.commit()

    # delete the test tokens
    for token in db.query(orm.APIToken):
        db.delete(token)
    db.commit()


@mark.role
async def test_load_roles_service_tokens_not_allowed(tmpdir, request):
    services = [{'name': 'some-service', 'api_token': 'secret-token'}]
    service_tokens = {
        'secret-token': 'some-service',
    }
    roles_to_load = [
        {
            'name': 'user-reader',
            'description': 'Read-only user models',
            'scopes': ['read:users'],
            'services': ['some-service'],
        },
        # 'culler' role has higher permissions that the token's owner 'some-service'
        {
            'name': 'culler',
            'description': 'Cull idle servers',
            'scopes': ['users:servers', 'admin:users:servers'],
            'tokens': ['secret-token'],
        },
    ]
    kwargs = {
        'load_roles': roles_to_load,
        'services': services,
        'service_tokens': service_tokens,
    }
    ssl_enabled = getattr(request.module, "ssl_enabled", False)
    if ssl_enabled:
        kwargs['internal_certs_location'] = str(tmpdir)
    hub = MockHub(**kwargs)
    hub.init_db()
    db = hub.db
    await hub.init_api_tokens()
    response = 'allowed'
    try:
        await hub.init_roles()
    except ValueError:
        response = 'denied'

    assert response == 'denied'

    # delete the test services
    for service in db.query(orm.Service):
        db.delete(service)
    db.commit()

    # delete the test tokens
    for token in db.query(orm.APIToken):
        db.delete(token)
    db.commit()


@mark.role
@mark.parametrize(
    "headers, role_list, status",
    [
        # no role requested - gets default 'user' role
        ({}, None, 200),
        # role scopes within the user's default 'user' role
        ({}, ['self-reader'], 200),
        # role scopes outside of the user's role but within the group's role scopes of which the user is a member
        ({}, ['users-reader'], 200),
        # non-existing role request
        ({}, ['non-existing'], 404),
        # role scopes outside of both user's role and group's role scopes
        ({}, ['users-creator'], 403),
    ],
)
async def test_get_new_token_via_api(app, headers, role_list, status):
    user = add_user(app.db, app, name='user')

    roles.add_role(app.db, {'name': 'self-reader', 'scopes': ['read:all']})
    roles.add_role(app.db, {'name': 'users-reader', 'scopes': ['read:users']})
    roles.add_role(app.db, {'name': 'users-creator', 'scopes': ['admin:users']})
    # add role for a group
    roles.add_role(app.db, {'name': 'group_role', 'scopes': ['read:users']})

    # create a group and add the user and group_role
    group = orm.Group.find(app.db, 'test_group')
    if not group:
        group = orm.Group(name='test_group')
        app.db.add(group)
        group.users.append(user)
        group_role = orm.Role.find(app.db, 'group_role')
        group.roles.append(group_role)
        app.db.commit()

    if role_list:
        body = json.dumps({'roles': role_list})
    else:
        body = ''
    # request a new token
    r = await api_request(
        app, 'users/user/tokens', method='post', headers=headers, data=body
    )
    assert r.status_code == status
    if status != 200:
        return
    # check the new-token reply for roles
    reply = r.json()
    assert 'token' in reply
    assert reply['user'] == 'user'
    if not role_list:
        assert reply['roles'] == ['user']
    else:
        assert reply['roles'] == role_list
    token_id = reply['id']

    # delete the token
    r = await api_request(app, 'users/user/tokens', token_id, method='delete')
    assert r.status_code == 204
    # verify deletion
    r = await api_request(app, 'users/user/tokens', token_id)
    assert r.status_code == 404
