import sqlite3
conn = sqlite3.connect('leads.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cur.fetchall()
print('TABLES:', tables)
for row in tables:
    name = row[0]
    cur.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,))
    print('SCHEMA', name, ':', cur.fetchone())
    cur.execute('SELECT COUNT(*) FROM [' + name + ']')
    print('ROWS:', cur.fetchone()[0])
conn.close()
