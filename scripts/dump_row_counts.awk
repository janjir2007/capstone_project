# Rows per table IN A PLAIN pg_dump (task 8.2b; shared since 8.2c by restore_test.sh and
# offsite_restore_test.sh, so the counting rule exists once).
# pg_dump writes one "COPY public.t (...) FROM stdin;" block per table (also for empty tables),
# one line per row (newlines inside values are escaped), ended by "\.".
# Input: the unzipped dump on stdin. Output: "<table> <rows>" per table (callers sort it).
/^COPY / { table = $2; rows = 0; inside = 1; next }
inside && /^\\\.$/ { print table, rows; inside = 0; next }
inside { rows++ }
