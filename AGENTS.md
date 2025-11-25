# NailGun - AI Agent Guide

**Project**: SatelliteQE NailGun  
**Repository**: https://github.com/SatelliteQE/nailgun

---

## Project Overview

**NailGun** is a GPL-licensed Python library that facilitates easy usage of the **Satellite 6 / Foreman API**. It provides an ORM-like (Object-Relational Mapping) interface for interacting with Red Hat Satellite and Foreman entities.

### Purpose
- Simplifies API interactions with Satellite 6 / Foreman
- Provides a Pythonic, object-oriented interface for API resources
- Abstracts away API inconsistencies and implementation details
- Contains workarounds for known API bugs
- Reduces verbose boilerplate code compared to raw HTTP requests

### Why NailGun?

The name "NailGun" comes from the philosophy: **Why use a hammer when you can use a nail gun?**

Challenges NailGun solves:
- **Verbose code**: General-purpose HTTP libraries require extensive boilerplate
- **Non-RESTful API**: Satellite's API isn't fully RESTful in design
- **Inconsistent implementation**: API endpoint behaviors vary significantly
- **Large API surface**: 405+ API paths as of latest count
- **Complex relationships**: Entity relationships require careful handling

### Key Features
- **Entity-based design**: Each Satellite resource is a Python class
- **CRUD operations**: Create, Read, Update, Delete via mixins
- **Relationship handling**: Automatic resolution of entity relationships
- **Smart payload generation**: Handles complex nested data structures
- **Task polling**: Automatic waiting for asynchronous operations
- **Configuration management**: Store and reuse server connection settings
- **Test data generation**: Built-in random data generation via FauxFactory

### Key Technologies
- **Requests**: HTTP library for API communication
- **FauxFactory**: Test data generation library
- **XDG**: Configuration file management (follows XDG Base Directory Specification)
- **Packaging**: Version comparison utilities
- **Inflection**: String pluralization utilities

---

## Architecture

NailGun follows a **layered modular architecture** with clear separation of concerns:

### Module Dependency Tree

```
nailgun.entities
└── nailgun.entity_mixins
    ├── nailgun.entity_fields
    ├── nailgun.config
    └── nailgun.client
```

Each module only knows about modules below it in the tree, creating a clean dependency hierarchy.

### Layer 1: Entity Layer (`entities.py`)
The top layer where entity classes are defined. Each class represents a Satellite/Foreman resource.

- **Purpose**: Provide high-level interface for working with Satellite resources
- **Location**: `nailgun/entities.py` (single large file)
- **Size**: 9000+ lines (reflects the size of Satellite's API)
- **Examples**: `Organization`, `Host`, `Repository`, `ActivationKey`, `ContentView`
- **Usage**: `org = Organization(server_config=cfg, name='MyOrg').create()`

### Layer 2: Mixin Layer (`entity_mixins.py`)
The middle layer providing CRUD functionality through mixins.

- **Purpose**: Implement common operations (create, read, update, delete, search)
- **Location**: `nailgun/entity_mixins.py`
- **Key Mixins**:
  - `Entity`: Base class for all entities
  - `EntityCreateMixin`: Implements `.create()`, `.create_json()`, `.create_raw()`
  - `EntityReadMixin`: Implements `.read()`, `.read_json()`, `.read_raw()`
  - `EntityUpdateMixin`: Implements `.update()`, `.update_json()`, `.update_raw()`
  - `EntityDeleteMixin`: Implements `.delete()`
  - `EntitySearchMixin`: Implements `.search()`

**Key Constants**:
- `TASK_TIMEOUT = 300`: Default timeout for task polling (5 minutes)
- `TASK_POLL_RATE = 5`: Seconds between polls
- `CREATE_MISSING = False`: Whether to auto-generate missing field values
- `DEFAULT_SERVER_CONFIG = None`: Global default server config

### Layer 3: Field Layer (`entity_fields.py`)
Defines field types that represent entity attributes and their types.

- **Purpose**: Type definitions, validation, and test data generation
- **Location**: `nailgun/entity_fields.py`
- **Field Types**:
  - `StringField`: Text values with configurable length and character types
  - `IntegerField`: Numeric values with optional min/max
  - `BooleanField`: True/False values
  - `DateField`, `DateTimeField`: Temporal values
  - `EmailField`, `IPAddressField`, `MACAddressField`: Specialized string fields
  - `OneToOneField`: Single related entity reference
  - `OneToManyField`: Multiple related entity references
  - `ListField`: List of values
  - `DictField`: Key-value pairs

### Layer 4: Communication Layer
Handles low-level HTTP communication and configuration.

- **Config** (`config.py`): Server connection configuration management
  - `ServerConfig`: Stores URL, auth, SSL verification, version
  - `BaseServerConfig`: Foundation for server communication
  - Configuration persistence to `~/.config/librobottelo/settings.json`
  
- **Client** (`client.py`): HTTP request wrappers
  - Wraps `requests` library methods (get, post, put, patch, delete)
  - Automatic JSON encoding/decoding
  - Request/response logging
  - Content-type management
  - SSL warning suppression for insecure connections

---

## Key Concepts

### 1. **Entities**

Entities are Python classes representing Satellite API resources. They behave like ORM models.

```python
from nailgun.config import ServerConfig
from nailgun.entities import Organization, Product, Repository

# Create server configuration
server_config = ServerConfig(
    url='https://satellite.example.com',
    auth=('admin', 'password'),
    verify=False  # Disable SSL verification (not recommended for production)
)

# Create an organization
org = Organization(
    server_config=server_config,
    name='Engineering',
    label='eng'
).create()

# Read organization details
org = Organization(server_config=server_config, id=1).read()
print(org.name)  # Access attributes like an ORM

# Update organization
org.description = 'Engineering department'
org = org.update(['description'])  # Only update specified fields

# Delete organization
org.delete()

# Search for organizations
orgs = Organization(server_config=server_config).search(
    query={'search': 'name="Engineering"'}
)
```

**Entity Structure**:
```python
class Organization(
    Entity,
    EntityCreateMixin,
    EntityReadMixin,
    EntityUpdateMixin,
    EntityDeleteMixin,
    EntitySearchMixin,
):
    """A representation of an Organization entity."""
    
    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': StringField(required=True),
            'label': StringField(),
            'description': StringField(),
            'title': StringField(),
        }
        self._meta = {
            'api_path': 'api/v2/organizations',
        }
        super().__init__(server_config=server_config, **kwargs)
```

### 2. **Mixins**

Mixins provide CRUD functionality. Each entity class inherits the mixins it needs.

**Available Mixins**:

| Mixin | Methods | Purpose |
|-------|---------|---------|
| `EntityCreateMixin` | `create()`, `create_json()`, `create_raw()`, `create_payload()`, `create_missing()` | Create entities on server |
| `EntityReadMixin` | `read()`, `read_json()`, `read_raw()` | Fetch entity data from server |
| `EntityUpdateMixin` | `update()`, `update_json()`, `update_raw()`, `update_payload()` | Modify existing entities |
| `EntityDeleteMixin` | `delete()` | Remove entities from server |
| `EntitySearchMixin` | `search()` | Query for multiple entities |

**Method Variants**:
- **Standard methods** (`.create()`, `.read()`, etc.): Return entity objects
- **`_json` methods** (`.create_json()`): Return JSON response as dict
- **`_raw` methods** (`.create_raw()`): Return raw `requests.Response` object
- **`_payload` methods** (`.create_payload()`): Generate JSON payload without sending

```python
# Standard usage - returns entity
org = Organization(server_config=config, name='Test').create()

# JSON response - returns dict
org_json = Organization(server_config=config, name='Test').create_json()

# Raw response - returns requests.Response
response = Organization(server_config=config, name='Test').create_raw()

# Just payload generation - returns dict
payload = Organization(server_config=config, name='Test').create_payload()
```

### 3. **Fields**

Fields define entity attributes, their types, validation rules, and test data generation.

```python
from nailgun.entity_fields import (
    BooleanField,
    IntegerField,
    ListField,
    OneToManyField,
    OneToOneField,
    StringField,
)

class Product(Entity, EntityCreateMixin, EntityReadMixin):
    """Represents a Satellite product."""
    
    def __init__(self, server_config=None, **kwargs):
        self._fields = {
            'name': StringField(
                required=True,           # Must be provided
                str_type='alpha',        # Use alphabetic characters
                length=(6, 12),          # 6-12 characters long
                unique=True              # Should be unique
            ),
            'label': StringField(),
            'description': StringField(),
            'gpg_key': OneToOneField('GPGKey'),  # Single related entity
            'organization': OneToOneField('Organization', required=True),
            'sync_plan': OneToOneField('SyncPlan'),
        }
        super().__init__(server_config=server_config, **kwargs)
        self._meta = {'api_path': 'katello/api/v2/products'}
```

**Field Parameters**:
- `required=True`: Must be provided when creating
- `default=value`: Default value if not provided
- `choices=(val1, val2)`: Restrict to specific values
- `unique=True`: Should be unique (for test data generation)

**StringField Special Parameters**:
- `str_type`: Character type (`'alpha'`, `'numeric'`, `'alphanumeric'`, `'utf8'`, `'latin1'`, etc.)
- `length`: `(min, max)` tuple or exact length integer

**IntegerField Special Parameters**:
- `min_val`: Minimum value
- `max_val`: Maximum value

### 4. **Server Configuration**

Manage connection settings with `ServerConfig`:

```python
from nailgun.config import ServerConfig

# Create configuration
config = ServerConfig(
    url='https://satellite.example.com',
    auth=('admin', 'password'),
    verify=True,  # Verify SSL certificates
    version='6.15'  # Optional: specify Satellite version for version-specific behavior
)

# Save configuration to disk (XDG config directory: ~/.config/librobottelo/)
config.save(label='production')

# Load configuration from disk
config = ServerConfig.get(label='production')

# Get configuration from XDG paths
config = ServerConfig.get()  # Loads 'default' label

# Use with entities
org = Organization(server_config=config, name='MyOrg').create()
```

**Configuration Storage**: 
- Location: `~/.config/librobottelo/settings.json`
- Format: JSON
- Thread-safe with file locking

**get_client_kwargs()**:
Returns a dict of kwargs suitable for passing to `requests` methods:
```python
kwargs = config.get_client_kwargs()
# Returns: {'auth': ('user', 'pass'), 'verify': False}
```

### 5. **Relationships**

NailGun handles entity relationships automatically, similar to Django ORM.

```python
# Create related entities
org = Organization(server_config=config, name='Acme').create()

# Pass entity object directly - NailGun resolves to ID
product = Product(
    server_config=config,
    name='RHEL',
    organization=org,  # Pass entire entity object
).create()

# Or pass ID directly
product = Product(
    server_config=config,
    name='RHEL',
    organization=org.id,  # Pass just the ID
).create()

# Access related entity attributes
print(product.organization.id)  # Access ID directly

# Fetch full related entity
org_details = product.organization.read()
print(org_details.name)  # 'Acme'

# One-to-many relationships
content_view = ContentView(server_config=config).create()
repo1 = Repository(...).create()
repo2 = Repository(...).create()

# Assign multiple related entities
content_view.repository = [repo1, repo2]
content_view = content_view.update(['repository'])

# Read related entities
for repo in content_view.read().repository:
    print(repo.name)
```

### 6. **Synchronous Operations and Task Polling**

Many Satellite operations are asynchronous and return a task. NailGun can wait for completion.

```python
# Sync a repository (asynchronous operation)
repo = Repository(server_config=config, id=5).read()

# Option 1: Synchronous mode (waits for completion)
result = repo.sync(synchronous=True, timeout=1800)  # 30 minutes
print(result['result'])  # 'success' or 'error'

# Option 2: Asynchronous with manual polling
task = repo.sync()  # Returns ForemanTask immediately
# ... do other work ...
result = task.poll(timeout=1800)  # Wait for completion later

# Option 3: Custom timeout for specific operation
from nailgun.entity_mixins import call_entity_method_with_timeout

call_entity_method_with_timeout(
    repo.sync,
    timeout=3600,  # 1 hour
    synchronous=True
)

# Change global default timeout
import nailgun.entity_mixins
nailgun.entity_mixins.TASK_TIMEOUT = 1800
```

**Task Exceptions**:
```python
from nailgun.entity_mixins import TaskFailedError, TaskTimedOutError

try:
    repo.sync(synchronous=True, timeout=300)
except TaskTimedOutError as e:
    print(f"Task {e.task_id} timed out")
except TaskFailedError as e:
    print(f"Task {e.task_id} failed")
```

### 7. **Search Queries**

Search for entities using Satellite's search syntax:

```python
# Search by name (exact match)
hosts = Host(server_config=config).search(
    query={'search': 'name=web01.example.com'}
)

# Search with wildcards
hosts = Host(server_config=config).search(
    query={'search': 'name=web*'}
)

# Search with multiple criteria
hosts = Host(server_config=config).search(
    query={'search': 'os="RHEL 9" and status.enabled=true'}
)

# Search with pagination
orgs = Organization(server_config=config).search(
    query={'per_page': 20, 'page': 2}
)

# Search all (no query)
all_orgs = Organization(server_config=config).search()

# Iterate through results
for host in hosts:
    print(f"{host.id}: {host.name}")
```

### 8. **Payload Generation**

Understand how NailGun generates API payloads:

```python
# Create entity but don't send yet
host = Host(
    server_config=config,
    name='web01',
    organization=org,  # Entity object
    location=location,   # Entity object
)

# Get the payload that would be sent
payload = host.create_payload()
print(payload)
# {
#     'host': {
#         'name': 'web01',
#         'organization_id': 1,  # Resolved to ID
#         'location_id': 2        # Resolved to ID
#     }
# }

# Manually modify payload if needed
payload['host']['comment'] = 'Custom field'

# Send custom payload
response = host.create_raw(create_missing=False)
```

**Payload Rules**:
- Entity relationships are converted to `<field>_id` format
- Only fields with values are included
- `None` values mean "delete this field" (for updates)
- Missing fields mean "don't touch this field" (for updates)

---

## Code Standards

### Import Ordering

1. **Standard library** imports
2. **Third-party** imports (alphabetical)
3. **NailGun** imports (alphabetical)
4. Blank line between groups

```python
# Standard library
import json
from datetime import datetime
from urllib.parse import urljoin

# Third-party
from fauxfactory import gen_alphanumeric, gen_string
from packaging.version import Version
import requests

# NailGun
from nailgun import client
from nailgun.config import ServerConfig
from nailgun.entity_fields import OneToOneField, StringField
from nailgun.entity_mixins import Entity, EntityCreateMixin
```

### Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| **Classes** | PascalCase | `Organization`, `ActivationKey`, `ContentView` |
| **Functions/Methods** | snake_case | `create()`, `read()`, `path()`, `gen_value()` |
| **Constants** | UPPER_SNAKE_CASE | `TASK_TIMEOUT`, `DEFAULT_SERVER_CONFIG`, `CREATE_MISSING` |
| **Private** | Leading underscore | `_poll_task()`, `_get_entity_ids()`, `_payload()` |
| **Entity Names** | **Singular** | `Host` (not `Hosts`), `Repository` (not `Repositories`) |
| **Module-level "private"** | Leading underscore | `_FAKE_YUM_REPO`, `_OPERATING_SYSTEMS` |

**Important**: Entity class names MUST be singular. This is a strict convention.

### Docstring Style

Use **reStructuredText** format with detailed parameter documentation:

```python
def create(self, create_missing=None):
    """Create an entity on the server.

    :param create_missing: Should values be generated for fields with a
        default value of ``None``? The default value for this argument
        changes depending on which values are provided when the entity is
        instantiated. See :meth:`nailgun.entity_mixins.Entity.__init__`.
    :return: An entity with all attributes populated.
    :rtype: nailgun.entities.Entity
    :raises: ``requests.exceptions.HTTPError`` if the server returns
        an HTTP 4XX or 5XX status code.
    """
```

### Code Style

- **Line length**: 100 characters (configured in `pyproject.toml`)
- **String quotes**: Single quotes `'` (Black default with `skip-string-normalization`)
- **Formatter**: Black
- **Linter**: Ruff with extensive rules
- **Target Python**: 3.11+

---

## Common Patterns

### Pattern 1: Basic CRUD Operations

```python
from nailgun.config import ServerConfig
from nailgun.entities import Organization

# Setup
config = ServerConfig(url='https://sat.example.com', auth=('admin', 'pass'))

# CREATE
org = Organization(server_config=config, name='DevOps', label='devops').create()
print(f"Created org with ID: {org.id}")

# READ
org = Organization(server_config=config, id=org.id).read()
print(f"Organization name: {org.name}")

# UPDATE
org.description = 'DevOps team organization'
org = org.update(['description'])  # Update only description field

# DELETE
org.delete()
```

### Pattern 2: Working with Relationships

```python
# Create organization
org = Organization(server_config=config, name='Engineering').create()

# Create product in organization
product = Product(
    server_config=config,
    name='RHEL Server',
    organization=org,  # Pass entity directly
).create()

# Create repository in product
repo = Repository(
    server_config=config,
    name='RHEL 9 BaseOS',
    product=product,  # Pass entity directly
    url='http://example.com/repo',
    content_type='yum',
).create()

# Access nested relationships
print(repo.product.read().name)  # "RHEL Server"
print(repo.product.organization.read().name)  # "Engineering"

# One-to-many relationships
ak = ActivationKey(server_config=config, organization=org).create()
ak.host_collection = [hc1, hc2]  # Multiple related entities
ak = ak.update(['host_collection'])
```

### Pattern 3: Search and Filter

```python
# Search all organizations
all_orgs = Organization(server_config=config).search()

# Search with query string
matching_orgs = Organization(server_config=config).search(
    query={'search': 'name~"Eng"'}  # Contains "Eng"
)

# Search with pagination
page_2 = Organization(server_config=config).search(
    query={'page': 2, 'per_page': 20}
)

# Iterate through results
for org in all_orgs:
    print(f"{org.id}: {org.name}")

# Advanced search syntax
hosts = Host(server_config=config).search(
    query={'search': 'os="RHEL 9" and environment=production'}
)
```

### Pattern 4: Synchronous Repository Sync

```python
# Create and sync repository
repo = Repository(
    server_config=config,
    name='Zoo Repo',
    product=product,
    url='http://example.com/zoo/',
    content_type='yum',
).create()

# Sync synchronously (waits for completion)
try:
    result = repo.sync(synchronous=True, timeout=1800)
    print(f"Sync result: {result['result']}")  # 'success'
except TaskFailedError as e:
    print(f"Sync failed: {e}")
except TaskTimedOutError as e:
    print(f"Sync timed out: {e}")

# Check sync status
repo = repo.read()
print(f"Last sync: {repo.last_sync}")
print(f"Content counts: {repo.content_counts}")
```

### Pattern 5: Creating Test Data with Auto-Generation

```python
from fauxfactory import gen_string

# Method 1: Explicit random data
org = Organization(
    server_config=config,
    name=gen_string('alpha', 10),  # Random 10-char alphabetic string
    label=gen_string('alphanumeric', 8).lower(),
).create()

# Method 2: Automatic generation with create_missing=True
org = Organization(server_config=config).create(create_missing=True)
# Name, label, etc. are auto-generated based on field definitions

# Method 3: Use field's gen_value() directly
from nailgun.entities import Organization
name_value = Organization.get_fields()['name'].gen_value()
org = Organization(server_config=config, name=name_value).create()

# For tests: Set global CREATE_MISSING
import nailgun.entity_mixins
nailgun.entity_mixins.CREATE_MISSING = True
org = Organization(server_config=config).create()  # Auto-generates values
```

### Pattern 6: Version-Specific Behavior

```python
from packaging.version import Version

# Set server version in config
config = ServerConfig(
    url='https://satellite.example.com',
    auth=('admin', 'password'),
    version='6.13'
)

# Check version in code
if config.version >= Version('6.10'):
    # Use newer API features
    pass
else:
    # Use older API or workarounds
    pass

# Entities can check version internally
class MyEntity(Entity):
    def create(self, create_missing=None):
        if self._server_config.version < Version('6.12'):
            # Apply workaround for older versions
            pass
        return super().create(create_missing)
```

### Pattern 7: Error Handling

```python
from requests.exceptions import HTTPError
from nailgun.entity_mixins import TaskFailedError, TaskTimedOutError

# HTTP errors (4XX, 5XX responses)
try:
    org = Organization(server_config=config, name='').create()
except HTTPError as e:
    print(f"HTTP Error: {e}")
    print(f"Status code: {e.response.status_code}")
    if e.response.status_code == 422:
        print("Validation error")
        print(e.response.json())  # Error details

# Task errors
try:
    repo.sync(synchronous=True, timeout=300)
except TaskTimedOutError as e:
    print(f"Task {e.task_id} timed out after 300s")
    # Task might still be running on server
except TaskFailedError as e:
    print(f"Task {e.task_id} failed")
    # Check task info for details

# Missing required fields
try:
    product = Product(server_config=config, name='Test').create()
except TypeError as e:
    print(f"Missing required field: {e}")
    # Missing 'organization' field
```

### Pattern 8: Custom Payloads and Low-Level Access

```python
from nailgun import client
from robottelo.config import get_credentials

# Get entity's API path
org = Organization(server_config=config, id=5)
path = org.path()  # '/api/v2/organizations/5'

# Make custom API calls using nailgun.client
response = client.get(
    path,
    auth=get_credentials(),
    verify=False
)
data = response.json()

# Bypass entity methods for special cases
payload = {
    'organization': {
        'name': 'CustomOrg',
        'custom_field': 'special_value'
    }
}
response = client.post(
    Organization(server_config=config).path('base'),
    payload,
    **config.get_client_kwargs()
)
```

---

## Entity Lifecycle

### Entity Creation Flow

1. **Instantiate entity** with required fields
2. **Call `.create()`** or `.create(create_missing=True)`
3. NailGun generates payload from fields using `create_payload()`
4. Sends POST request to API endpoint
5. Parses response and populates entity attributes
6. Returns entity instance with server-provided data (ID, timestamps, etc.)

```python
# Step 1: Instantiate
org = Organization(server_config=config, name='MyOrg')
# At this point: org has name, but no id, created_at, etc.

# Step 2: Create (sends to server)
org = org.create()

# Step 3: Entity now has full server data
print(org.id)          # e.g., 42
print(org.created_at)  # Timestamp from server
print(org.updated_at)  # Timestamp from server
print(org.label)       # Auto-generated by server
```

### Entity Update Flow

1. **Read entity** from server (recommended to get current state)
2. **Modify attributes** locally
3. **Call `.update(fields)`** with list of fields to update
4. NailGun generates payload with **only specified fields**
5. Sends PUT request to API
6. Returns updated entity with fresh server data

```python
# Step 1: Read current state
org = Organization(server_config=config, id=5).read()

# Step 2: Modify locally
org.description = 'Updated description'
org.title = 'New Title'

# Step 3: Update specific fields only
org = org.update(['description', 'title'])

# Only 'description' and 'title' are sent to server
# Other fields remain unchanged on server
```

**Update vs. Create Payload Difference**:
- **Create**: Includes all fields with values
- **Update**: Includes only fields specified in `fields` parameter

### Entity Deletion Flow

1. **Have entity with ID** (from `.create()` or `.read()`)
2. **Call `.delete()`**
3. NailGun sends DELETE request to API
4. Entity is removed from server
5. For async deletions, polls task until complete

```python
# Method 1: Delete by ID
Organization(server_config=config, id=5).delete()

# Method 2: Delete instance
org = Organization(server_config=config, id=5).read()
org.delete()

# Method 3: Delete right after creation
org = Organization(server_config=config, name='Temp').create()
org.delete()
```

### Entity Read Flow

1. **Create entity instance with ID**
2. **Call `.read()`**
3. NailGun sends GET request to API
4. Parses JSON response
5. Populates all entity attributes from response
6. Returns entity with full data

```python
# Just ID initially
org = Organization(server_config=config, id=5)

# Read from server
org = org.read()

# Now has all attributes
print(org.name)
print(org.description)
print(org.created_at)
```

---

## Usage in Robottelo

NailGun is primarily used through Robottelo's `target_sat.api` interface:

### Robottelo Integration Pattern

```python
def test_example(target_sat):
    """Test using target_sat fixture."""
    # target_sat.api provides pre-configured entity classes
    # with server_config already set to target_sat
    
    # Create entities
    org = target_sat.api.Organization(name='TestOrg').create()
    
    # No need to pass server_config - it's automatic!
    product = target_sat.api.Product(
        name='RHEL',
        organization=org
    ).create()
    
    # All NailGun methods work
    product.description = 'Updated'
    product = product.update(['description'])
    
    # Cleanup
    product.delete()
    org.delete()
```

### Common Robottelo Patterns

```python
# Pattern 1: Using module_org fixture
def test_with_org(module_org, target_sat):
    """Use shared organization."""
    product = target_sat.api.Product(
        organization=module_org  # Reuse org from fixture
    ).create()

# Pattern 2: Reading existing entities
def test_read_default_org(target_sat):
    """Find and read existing entity."""
    orgs = target_sat.api.Organization().search(
        query={'search': 'name="Default Organization"'}
    )
    org = orgs[0].read()

# Pattern 3: Repository sync with timeout
def test_repo_sync(module_product, target_sat):
    """Sync repository with extended timeout."""
    from nailgun.entity_mixins import call_entity_method_with_timeout
    
    repo = target_sat.api.Repository(product=module_product).create()
    call_entity_method_with_timeout(
        repo.sync,
        timeout=1800,
        synchronous=True
    )

# Pattern 4: Using API factory methods
def test_with_factory(target_sat):
    """Use Robottelo's API factory helpers."""
    # Robottelo adds convenience methods
    repo_id = target_sat.api_factory.enable_rhrepo_and_fetchid(
        basearch='x86_64',
        org_id=org.id,
        product='Red Hat Enterprise Linux Server',
        repo='Red Hat Enterprise Linux 9 for x86_64 - BaseOS (RPMs)',
        reposet='Red Hat Enterprise Linux 9 for x86_64 - BaseOS (RPMs)',
        releasever='9',
    )
    repo = target_sat.api.Repository(id=repo_id).read()
```

### Direct NailGun Usage

```python
# When you need direct control without Robottelo
from nailgun.config import ServerConfig
from nailgun.entities import Organization

config = ServerConfig(
    url='https://satellite.example.com',
    auth=('admin', 'password'),
    verify=False
)

org = Organization(server_config=config, name='DirectOrg').create()
```

---

## Testing with NailGun

### Unit Tests

NailGun's unit tests use `pytest` and mock HTTP responses:

```python
import pytest
from unittest.mock import Mock, patch
from nailgun.entities import Organization
from nailgun.config import ServerConfig

def test_organization_create():
    """Test organization creation."""
    config = Mock(spec=ServerConfig)
    config.url = 'https://example.com'
    config.get_client_kwargs.return_value = {'auth': ('user', 'pass')}
    
    org = Organization(server_config=config, name='Test')
    
    with patch('nailgun.client.post') as mock_post:
        mock_post.return_value.json.return_value = {
            'id': 1,
            'name': 'Test',
            'label': 'test',
            'description': None
        }
        result = org.create()
        
    assert result.id == 1
    assert result.name == 'Test'
    mock_post.assert_called_once()
```

### Integration Tests (Robottelo Style)

```python
import pytest
from nailgun.entity_mixins import TaskFailedError

def test_create_product_with_repo(target_sat):
    """Test product and repository creation and sync."""
    # Create organization
    org = target_sat.api.Organization(name='TestOrg').create()
    
    # Create product
    product = target_sat.api.Product(
        name='TestProduct',
        organization=org,
    ).create()
    
    # Create repository
    repo = target_sat.api.Repository(
        name='TestRepo',
        product=product,
        url='http://example.com/repo/',
        content_type='yum',
    ).create()
    
    # Sync repository
    try:
        repo.sync(synchronous=True, timeout=600)
    except TaskFailedError:
        pytest.fail("Repository sync failed")
    
    # Verify content
    repo = repo.read()
    assert repo.content_counts['rpm'] > 0
    
    # Cleanup
    repo.delete()
    product.delete()
    org.delete()
```

---

## Advanced Topics

### Custom Entity Path Methods

Many entities override the `path()` method for custom endpoints:

```python
class ActivationKey(Entity, EntityCreateMixin):
    def path(self, which=None):
        """Extend paths for custom endpoints."""
        if which in ('content_override', 'copy', 'releases'):
            return f'{super().path(which="self")}/{which}'
        return super().path(which)
    
    def copy(self, synchronous=True, timeout=None, **kwargs):
        """Copy this activation key."""
        kwargs.update(self._server_config.get_client_kwargs())
        response = client.post(self.path('copy'), **kwargs)
        return _handle_response(response, self._server_config, synchronous, timeout)
```

**Common `which` values**:
- `'base'`: Base collection path (e.g., `/api/v2/organizations`)
- `'self'`: Specific instance path (e.g., `/api/v2/organizations/5`)
- Custom values for entity-specific endpoints

### Custom Payload Methods

Override payload generation for special handling:

```python
class ActivationKey(Entity):
    def update_payload(self, fields=None):
        """Customize update payload."""
        payload = super().update_payload(fields)
        # Always include organization_id for AK updates
        payload['organization_id'] = self.organization.id
        return payload
```

### Version-Specific Workarounds

```python
from nailgun.entities import _get_version
from packaging.version import Version

class Repository(Entity):
    def sync(self, synchronous=True, timeout=None, **kwargs):
        """Sync repository with version-specific handling."""
        version = _get_version(self._server_config)
        
        if version < Version('6.10'):
            # Apply workaround for old version bug
            # BZ#1234567
            pass
        
        return super().sync(synchronous, timeout, **kwargs)
```

### Task Polling Customization

```python
# Change global defaults
import nailgun.entity_mixins
nailgun.entity_mixins.TASK_TIMEOUT = 1800  # 30 minutes
nailgun.entity_mixins.TASK_POLL_RATE = 10  # Poll every 10 seconds

# Use call_entity_method_with_timeout for one-off changes
from nailgun.entity_mixins import call_entity_method_with_timeout

call_entity_method_with_timeout(
    repo.sync,
    timeout=3600,  # 1 hour for this specific sync
    synchronous=True
)
```

### Accessing Raw Client Methods

```python
from nailgun import client

# Direct HTTP calls
response = client.get(
    'https://satellite.example.com/api/v2/status',
    auth=('admin', 'password'),
    verify=False
)
status = response.json()

# With server config
response = client.post(
    org.path('custom_endpoint'),
    {'data': 'value'},
    **config.get_client_kwargs()
)
```

---

## Troubleshooting

### Common Issues

#### 1. **Missing Required Fields**

**Problem**: `TypeError: A value must be provided for the "organization" field`

**Solution**: Ensure all required fields are provided:

```python
# ❌ BAD: Missing required organization field
product = Product(server_config=config, name='MyProduct').create()

# ✅ GOOD: Include required fields
org = Organization(server_config=config, name='MyOrg').create()
product = Product(
    server_config=config,
    name='MyProduct',
    organization=org  # Required field
).create()
```

#### 2. **SSL Verification Errors**

**Problem**: `SSLError: [SSL: CERTIFICATE_VERIFY_FAILED]`

**Solution**: Either use valid certificates or disable verification:

```python
# For development/testing only - disable SSL verification
config = ServerConfig(
    url='https://satellite.example.com',
    auth=('admin', 'password'),
    verify=False  # Disables SSL verification
)

# Production: Use valid certificates and verify=True
```

**Note**: The `nailgun.client` module suppresses `InsecureRequestWarning` to avoid training users to ignore warnings.

#### 3. **Task Timeout Errors**

**Problem**: `TaskTimedOutError: Timed out polling task <id>`

**Solution**: Increase timeout for long-running operations:

```python
# Method 1: Inline timeout
repo.sync(synchronous=True, timeout=3600)  # 1 hour

# Method 2: Use helper
from nailgun.entity_mixins import call_entity_method_with_timeout
call_entity_method_with_timeout(repo.sync, timeout=3600, synchronous=True)

# Method 3: Change global default
import nailgun.entity_mixins
nailgun.entity_mixins.TASK_TIMEOUT = 3600
```

#### 4. **Entity Relationship Errors**

**Problem**: `AttributeError` or `KeyError` when accessing related entity attributes

**Solution**: Call `.read()` on related entities to fetch full data:

```python
# ❌ BAD: Related entity might not have all attributes loaded
product_name = repo.product.name  # May fail

# ✅ GOOD: Explicitly read related entity
product = repo.product.read()
product_name = product.name

# Alternative: Check if attribute exists
if hasattr(repo.product, 'name'):
    product_name = repo.product.name
else:
    product_name = repo.product.read().name
```

#### 5. **Update Not Working**

**Problem**: `.update()` doesn't change field on server

**Solution**: Make sure to pass field names to `update()`:

```python
# ❌ BAD: Forgot to specify fields
org.description = 'New description'
org.update()  # Won't update anything!

# ✅ GOOD: Specify which fields to update
org.description = 'New description'
org = org.update(['description'])

# ✅ ALSO GOOD: Update multiple fields
org.description = 'New description'
org.title = 'New Title'
org = org.update(['description', 'title'])
```

#### 6. **None vs. Missing Field**

**Problem**: Confusion between `None` and missing fields

**Understanding**:
```python
# These have DIFFERENT effects:
org.description = None
org.update(['description'])  # Deletes description on server

del org.description
org.update(['description'])  # Doesn't touch description on server
```

#### 7. **HTTPError with No Details**

**Problem**: `HTTPError` exception doesn't show error details

**Solution**: Use the enhanced error handling:

```python
from nailgun.entity_mixins import raise_for_status_add_to_exception
from requests.exceptions import HTTPError

try:
    org = Organization(server_config=config, name='').create()
except HTTPError as e:
    print(f"Status: {e.response.status_code}")
    print(f"Response: {e.response.text}")
    if e.args:  # NailGun adds JSON to args
        print(f"Error details: {e.args[-1]}")
```

---

## Best Practices

### DO ✅

- **Use ServerConfig objects** to manage connection settings consistently
- **Save and reuse configurations** via `config.save(label='name')`
- **Pass entity objects as relationships** instead of just IDs (NailGun handles conversion)
- **Use `create_missing=True`** for test data generation
- **Handle exceptions appropriately** (HTTPError, TaskFailedError, TaskTimedOutError)
- **Update only changed fields** with `.update(['field1', 'field2'])`
- **Use synchronous mode** for operations where you need immediate results
- **Specify timeouts** for long-running operations explicitly
- **Read entities before updating** to ensure you have current state
- **Use singular entity names** (`Host` not `Hosts`)
- **Set `required=True`** for fields that are actually required by the API
- **Use appropriate `str_type`** for StringFields (`'alpha'` for names, `'alphanumeric'` for labels)
- **Write comprehensive docstrings** in reStructuredText format

### DON'T ❌

- **Don't hardcode credentials** - use ServerConfig and save/load
- **Don't ignore SSL verification in production** - only use `verify=False` for testing
- **Don't update entities without reading first** - you might overwrite concurrent changes
- **Don't forget to delete test entities** - use cleanup/teardown or finalizers
- **Don't use plural entity names** - use `Host` not `Hosts` (strict convention)
- **Don't access nested attributes without `.read()`** - related entities may not be fully loaded
- **Don't set `required=False` for actually required fields** - keep API contracts clear
- **Don't skip error handling** - API calls can and do fail
- **Don't use `time.sleep()`** - use task polling with timeouts
- **Don't modify `_fields` or `_meta` after `__init__`** - these are set once
- **Don't call entity methods without server_config** - always provide it or use default
- **Don't assume field order matters** - it doesn't, they're dicts

---

## Development Conventions

### Linting and Code Quality

*   **Formatter:** Black with line length of 100 characters
    - Run: `black .`
    - Configuration: `pyproject.toml`
    - String normalization: Skipped (keeps single quotes)

*   **Linter:** Ruff with extensive rule set
    - Target Python version: 3.11
    - Run: `ruff check .`
    - Rules: See `pyproject.toml` for complete list
    - Key checks: docstrings (D*), complexity (C*), performance (PERF*), pycodestyle (E*, W*)

*   **Pre-commit Hooks:** Configured in `.pre-commit-config.yaml`
    - Install: `pre-commit install`
    - Run manually: `pre-commit run --all-files`
    - Hooks: ruff-check, ruff-format, check-yaml, debug-statements

### Testing

*   **Test Framework:** pytest
*   **Test Location:** `tests/` directory
*   **Run Tests:** `make test` or `pytest tests/`
*   **Coverage:** Track with codecov
*   **Test Files**: `test_*.py` in `tests/`
*   **Key Test Modules**:
    - `test_entities.py`: Entity behavior tests
    - `test_entity_mixins.py`: Mixin functionality tests
    - `test_entity_fields.py`: Field type tests
    - `test_config.py`: Configuration management tests
    - `test_client.py`: HTTP client tests

### Documentation

*   **Build Docs:** `make docs-html`
*   **View Docs:** Open `docs/_build/html/index.html`
*   **Doc Format:** Sphinx with reStructuredText
*   **API Docs**: Auto-generated from docstrings
*   **Examples**: Located in `docs/examples.rst`

### Version Control and Review Process

*   **Review Process:** Minimum **two ACKs** required for merge
    - At least one must be from a **Tier 2 reviewer**
    - All comments must be resolved
*   **Commit Guidelines:**
    - Keep commits small and coherent
    - One commit per issue
    - Write clear commit messages (follow [conventional commit](https://www.conventionalcommits.org/) format when possible)
    - Rebasing is encouraged over merging
*   **PR Requirements:**
    - Must pass Travis CI checks
    - Must include unit tests for new entities/functionality
    - Must provide test results from Satellite API (interactive shell output acceptable)
    - Should specify applicable branches (master, 6.X.z branches)
*   **CI/CD**: Travis CI for automated testing, pre-commit.ci for auto-fixes

### Contributing Guidelines

1. **Code Standards**:
   - Maintain PEP8 compliance (enforced by Ruff)
   - All entity names must be **singular**
   - All required attributes must have `required=True`
   - Prefer `'alpha'` str_type for string defaults (easier debugging)
   - Document workarounds with corresponding BZ/Issue ID

2. **Unit Tests**:
   - Compulsory for all new entities
   - Should cover all available actions (create, read, update, delete, search, custom methods)

3. **Documentation**:
   - Add usage examples in docstrings
   - Provide interactive Python shell output or test results in PR description

4. **Version Labels**:
   - Set appropriate Foreman/Satellite version labels when applicable

---

## Additional Resources

- **Documentation**: https://nailgun.readthedocs.io/
- **Repository**: https://github.com/SatelliteQE/nailgun
- **Issues**: https://github.com/SatelliteQE/nailgun/issues
- **PyPI**: https://pypi.org/project/nailgun/
- **Robottelo** (Primary Consumer): https://github.com/SatelliteQE/robottelo
- **Foreman API Docs**: Your-Satellite-URL/apidoc/v2
- **IRC**: #robottelo on Libera.Chat
- **Related Projects**:
  - Airgun (UI automation): https://github.com/SatelliteQE/airgun
  - Broker (VM provisioning): https://github.com/SatelliteQE/broker

---

## Quick Reference

### Common Entity Methods

| Method | Purpose | Returns | Example |
|--------|---------|---------|---------|
| `.create()` | Create entity on server | Entity object | `org.create()` |
| `.create(create_missing=True)` | Create with auto-generated values | Entity object | `org.create(create_missing=True)` |
| `.read()` | Fetch entity from server | Entity object | `org.read()` |
| `.update(fields)` | Update specific fields | Entity object | `org.update(['name'])` |
| `.delete()` | Delete entity from server | None or task info | `org.delete()` |
| `.search(query)` | Search for entities | List of entities | `Organization().search()` |
| `.path(which)` | Get API path | String | `org.path('self')` |
| `.create_payload()` | Generate JSON payload | Dict | `org.create_payload()` |

### Common Field Types

| Field | Purpose | Common Parameters | Example |
|-------|---------|-------------------|---------|
| `StringField` | Text values | `required`, `str_type`, `length`, `unique` | `name = StringField(required=True, str_type='alpha')` |
| `IntegerField` | Numeric values | `min_val`, `max_val`, `default` | `count = IntegerField(min_val=0, max_val=100)` |
| `BooleanField` | True/False | `default` | `enabled = BooleanField(default=True)` |
| `OneToOneField` | Single related entity | `required`, entity class name | `org = OneToOneField('Organization', required=True)` |
| `OneToManyField` | Multiple related entities | entity class name | `hosts = OneToManyField('Host')` |
| `ListField` | List of values | `default` | `tags = ListField()` |
| `EmailField` | Email addresses | Standard field params | `email = EmailField()` |
| `IPAddressField` | IP addresses | Standard field params | `ip = IPAddressField()` |
| `DateField` | Date values | `min_date`, `max_date` | `start_date = DateField()` |
| `DateTimeField` | DateTime values | `min_date`, `max_date` | `created_at = DateTimeField()` |

### ServerConfig Quick Reference

```python
# Create configuration
config = ServerConfig(
    url='https://satellite.example.com',  # Required
    auth=('admin', 'password'),            # Required
    verify=False,                          # SSL verification (default: True)
    version='6.15'                         # Satellite version (optional)
)

# Save configuration (to ~/.config/librobottelo/settings.json)
config.save(label='production')

# Load configuration
config = ServerConfig.get(label='production')

# Get client kwargs for requests
kwargs = config.get_client_kwargs()  # {'auth': (...), 'verify': False}
```

### Task Polling Quick Reference

```python
# Synchronous (wait for completion)
result = repo.sync(synchronous=True, timeout=1800)

# Asynchronous (get task, poll later)
task = repo.sync()
result = task.poll(timeout=1800)

# Custom timeout for one operation
from nailgun.entity_mixins import call_entity_method_with_timeout
call_entity_method_with_timeout(repo.sync, timeout=3600, synchronous=True)

# Change global timeout
import nailgun.entity_mixins
nailgun.entity_mixins.TASK_TIMEOUT = 1800
nailgun.entity_mixins.TASK_POLL_RATE = 10
```

### Exception Handling Quick Reference

```python
from requests.exceptions import HTTPError
from nailgun.entity_mixins import TaskFailedError, TaskTimedOutError

try:
    org = Organization(...).create()
except HTTPError as e:
    # HTTP 4XX or 5XX errors
    print(e.response.status_code)
    print(e.response.json())

try:
    repo.sync(synchronous=True, timeout=300)
except TaskTimedOutError as e:
    # Task didn't complete in time
    print(f"Task {e.task_id} timed out")
except TaskFailedError as e:
    # Task completed with error
    print(f"Task {e.task_id} failed")
```

---

**Last Updated**: 2025-11-25  
**Maintainers**: SatelliteQE Team  
**Python Version**: 3.10, 3.11, 3.12  
**License**: GPL
