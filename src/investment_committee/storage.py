"""The single door to the SQLite database (ADR-0003, owner @gunaphysics).

Owns the schema and the code that builds the database on first run from the
committed sample data. Every read and write in the project goes through this
module; no other code opens a connection or touches a table.
"""
