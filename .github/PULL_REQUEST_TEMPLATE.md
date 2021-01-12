##### Description of changes

Describe in detail the changes made, and any potential impacts to callers.

##### Upstream API documentation, plugin, or feature links

Link to any relevant upstream API documentation that relates to the content of the PR.

##### Functional demonstration

Provide an execution of the modified code, with ipython code blocks or screen shots.
You can exercise the code as raw API calls or using any other method.

Your contribution should include updates to the unit tests, covering the modified portions or adding new coverage.

Example:
```
# Demonstrate functional Snapshot read in ipython
In [1]: from nailgun.entities import Snapshot
In [2]: Snapshot(host='sat.instance.addr.com', id='snap_uuid').read()
Out [2]: <read method result>
```

##### Additional Information

Any additional notes for reviewers, comments about the change, TODO lists on WIP PRs, etc.
