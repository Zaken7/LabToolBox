import bcrypt
import base64

# Generate a proper bcrypt hash for the password 'admin'
password = 'admin'
salt = bcrypt.gensalt()
hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
hash_str = hashed.decode('utf-8')
b64_encoded = base64.b64encode(hashed).decode('utf-8')

print('Raw bcrypt hash:', hash_str)
print('Base64 encoded for YAML:', b64_encoded)

# Verify it works
test_result = bcrypt.checkpw(password.encode('utf-8'), hashed)
print('Hash verification test:', test_result)
"
