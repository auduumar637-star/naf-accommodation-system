from werkzeug.security import generate_password_hash

print("AO:", generate_password_hash("ao123"))
print("Commander:", generate_password_hash("cmd123"))
print("OC:", generate_password_hash("oc123"))
print("Supervisor:", generate_password_hash("sup123"))