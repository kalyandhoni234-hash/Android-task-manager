"""Live storage monitoring: the internal shared volume (``/data``).

The static storage facts of the Device page (collected once per connection
session) live in ``device``; this package adds the LIVE view — the same
``df -k /data`` read sampled on its own slow cadence, so the dashboard can
show utilization moving over time without inventing a second parse path.
"""

from .collector import StorageCollector
from .models import StorageSnapshot

__all__ = ["StorageCollector", "StorageSnapshot"]
