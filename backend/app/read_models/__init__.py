"""Read-models: each answers one page's question from stored data.

A read-model reads and formats, and writes nothing. A route handler around
one only does HTTP work: it reads the parameters, calls one read function,
turns ``TickerNotFound`` into a 404 and declares the response model.
"""
