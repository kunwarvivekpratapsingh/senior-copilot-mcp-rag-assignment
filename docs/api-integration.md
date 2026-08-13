# API integration

The Alarm Management API contract, derived from the three Postman collections in
`postman/`, which are the specification for the simulator built in
`services/alarm-simulator/`.

Covers: base URL and versioning, authentication, trace headers, the full endpoint
inventory, request and response shapes, pagination semantics, the error envelope, and
the enumerations the collections rely on.

> **Pending — authored in build step 2 (simulator), before the code it describes.**

The acceptance gate for this contract is `make contract`, which runs all three
collections against a running simulator with newman.
