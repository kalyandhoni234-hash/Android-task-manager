"""ADB integration layer.

Only code in this package is allowed to import ``subprocess``. Everything else
talks to ADB through the ConnectionManager or a compatible ``CommandRunner``.
"""