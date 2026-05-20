import os
from flask import Flask, render_template, request, jsonify, session, redirect
from db import get_connection
from werkzeug.security import generate_password_hash, check_password_hash
from email_utils import send_email
app = Flask(__name__)


app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "fallbacksecret")
# ================= PAGE ROUTES =================


def require_login(role=None):
    if 'role' not in session:
        return False

    if role and session.get('role') != role:
        return False

    return True


@app.route('/')
def home():
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    return render_template('personnel_dashboard.html')


@app.route('/ao')
def ao():
    return render_template('ao_dashboard.html')


@app.route('/commander')
def commander():
    return render_template('commander_dashboard.html')


@app.route('/oc')
def oc():
    return render_template('oc_dashboard.html')


@app.route('/supervisor')
def supervisor():
    return render_template('supervisor_dashboard.html')


# ================= AUTH ROUTES =================

@app.route('/register', methods=['POST'])
def register():
    data = request.json

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            INSERT INTO personnel (fullname, service_number, email, password, category)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            data['fullname'],
            data['service_number'],
            data['email'],
            generate_password_hash(data['password']),
            data['rank']
        ))

        conn.commit()
        return jsonify({"message": "Registered successfully"})

    except:
        conn.rollback()
        return jsonify({"error": "Service number exists"}), 400

    finally:
        cur.close()
        conn.close()


@app.route('/login', methods=['POST'])
def login():
    data = request.json

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, password FROM personnel WHERE service_number=%s
    """, (data['service_number'],))

    user = cur.fetchone()

    cur.close()
    conn.close()

    if user and check_password_hash(user[1], data['password']):
        session['user_id'] = user[0]
        session['role'] = 'personnel'

        return jsonify({"message": "Login success"})
    else:
        return jsonify({"error": "Invalid credentials"}), 401


@app.route('/admin/login', methods=['POST'])
def admin_login():
    data = request.json

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, password, role
        FROM admins
        WHERE username = %s
    """, (data['username'],))

    admin = cur.fetchone()

    cur.close()
    conn.close()

    if admin and check_password_hash(admin[1], data['password']):
        session['admin_id'] = admin[0]
        session['role'] = admin[2]

        return jsonify({
            "message": "Login successful",
            "role": admin[2]
        })
    else:
        return jsonify({"error": "Invalid admin credentials"}), 401


# ================= APPLICATION =================

from psycopg2.errors import UniqueViolation

@app.route('/personnel/apply', methods=['POST'])
def apply():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 403

    data = request.get_json()
    acc_type = data.get("type")

    conn = get_connection()
    cur = conn.cursor()

    try:
        # check if already has accommodation
        cur.execute("SELECT 1 FROM accommodations WHERE occupant_id=%s", (session['user_id'],))
        if cur.fetchone():
            return jsonify({"error": "You already have accommodation"}), 400

        # insert application (DB constraint will enforce rule)
        cur.execute("""
            INSERT INTO applications (personnel_id, type, status)
            VALUES (%s, %s, 'pending')
        """, (session['user_id'], acc_type))

        conn.commit()

    except UniqueViolation:
        conn.rollback()
        return jsonify({"error": "You already have an active application"}), 400

    finally:
        cur.close()
        conn.close()

    return jsonify({"message": "Application submitted successfully"})

@app.route('/personnel/application-status')
def status():
    if 'user_id' not in session:
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT status
        FROM applications
        WHERE personnel_id=%s
        ORDER BY id DESC
        LIMIT 1
    """, (session['user_id'],))

    row = cur.fetchone()

    cur.close()
    conn.close()

    if not row:
        return jsonify({"status": "No application"})

    return jsonify({"status": row[0]})

# ================= SUBMIT COMPLAINT =================

@app.route('/personnel/complain', methods=['POST'])
def complaint():
    if not require_login('personnel'):
        return jsonify({"error": "Unauthorized"}), 403

    data = request.json

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO complaints (personnel_id, message)
        VALUES (%s, %s)
    """, (session['user_id'], data['message']))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "Complaint submitted"})

# ================= SUPERVISOR =================

# Get complaints from personnel
@app.route('/supervisor/complaints')
def supervisor_complaints():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.id, p.fullname, p.service_number,
               a.block, a.flat_number, c.message
        FROM complaints c
        JOIN personnel p ON c.personnel_id = p.id
        LEFT JOIN accommodations a ON a.occupant_id = p.id
        WHERE c.stage = 'supervisor'
    """)

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "id": d[0],
            "name": d[1],
            "service_number": d[2],
            "block": d[3],
            "flat": d[4],
            "message": d[5]
        }
        for d in data
    ])


# Forward to OC
@app.route('/supervisor/forward/<int:id>', methods=['POST'])
def supervisor_forward(id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("UPDATE complaints SET stage='oc' WHERE id=%s", (id,))
    conn.commit()

    cur.close()
    conn.close()

    return jsonify({"message": "Forwarded to OC Works"})


# Reject
@app.route('/supervisor/reject/<int:id>', methods=['POST'])
def supervisor_reject(id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE complaints
        SET status='rejected'
        WHERE id=%s
    """, (id,))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "Complaint rejected"})
@app.route('/supervisor/history')
def supervisor_history():

    if not require_login('Supervisor'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            p.fullname,
            p.service_number,
            a.block,
            a.flat_number,
            c.message,
            c.status

        FROM complaints c

        JOIN personnel p
            ON c.personnel_id = p.id

        LEFT JOIN accommodations a
            ON a.occupant_id = p.id

        WHERE c.stage IN ('oc_works', 'ao', 'commander', 'resolved')

        ORDER BY c.id DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "name": r[0],
            "service_number": r[1],
            "block": r[2] or "-",
            "flat": r[3] or "-",
            "message": r[4],
            "status": r[5]
        }
        for r in rows
    ])

# ================= OC WORKS =================

@app.route('/oc/incoming')
def oc_incoming():

    if not require_login('OC Works'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            c.id,
            p.fullname,
            p.service_number,
            a.block,
            a.flat_number,
            c.message,
            c.status
        FROM complaints c
        JOIN personnel p
            ON c.personnel_id = p.id
        LEFT JOIN accommodations a
            ON a.occupant_id = p.id
        WHERE c.stage = 'oc'
        ORDER BY c.id DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "id": r[0],
            "name": r[1],
            "service_number": r[2],
            "block": r[3] or "-",
            "flat_number": r[4] or "-",
            "message": r[5],
            "status": r[6]
        }
        for r in rows
    ])

@app.route('/oc/complaints')
def oc_complaints():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.id, p.fullname, p.service_number,
               a.block, a.flat_number, c.message
        FROM complaints c
        JOIN personnel p ON c.personnel_id = p.id
        LEFT JOIN accommodations a ON a.occupant_id = p.id
        WHERE c.stage = 'oc'
    """)

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "id": d[0],
            "name": d[1],
            "service_number": d[2],
            "block": d[3],
            "flat": d[4],
            "message": d[5]
        }
        for d in data
    ])

@app.route('/oc/forward/<int:id>', methods=['POST'])
def oc_forward(id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("UPDATE complaints SET stage='ao' WHERE id=%s", (id,))
    conn.commit()

    cur.close()
    conn.close()

    return jsonify({"message": "Forwarded to AO"})


@app.route('/oc/reject/<int:id>', methods=['POST'])
def oc_reject(id):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE complaints
        SET status='rejected'
        WHERE id=%s
    """, (id,))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "Rejected by OC Works"})


@app.route('/oc/processed')
def oc_processed():

    if not require_login('OC Works'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            c.id,
            p.fullname,
            p.service_number,
            a.block,
            a.flat_number,
            c.message,
            c.status
        FROM complaints c
        JOIN personnel p
            ON c.personnel_id = p.id
        LEFT JOIN accommodations a
            ON a.occupant_id = p.id
        WHERE c.stage IN ('ao', 'resolved')
        ORDER BY c.id DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "id": r[0],
            "name": r[1],
            "service_number": r[2],
            "block": r[3] or "-",
            "flat_number": r[4] or "-",
            "message": r[5],
            "status": r[6]
        }
        for r in rows
    ])


# ================= AO =================

@app.route('/ao/applications')
def ao_applications():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.id, a.personnel_id, p.fullname, p.service_number, a.type
        FROM applications a
        JOIN personnel p ON a.personnel_id = p.id
        WHERE a.status = 'pending'
        ORDER BY a.id DESC
    """)

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "id": d[0],
            "personnel_id": d[1],
            "name": d[2],
            "service_number": d[3],
            "type": d[4]
        } for d in data
    ])

@app.route('/ao/houses/<type>')
def get_houses(type):
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, block, flat_number
        FROM accommodations
        WHERE occupied = FALSE AND category = %s
    """, (type,))

    houses = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "id": h[0],
            "block": h[1],
            "flat": h[2]
        }
        for h in houses
    ])
   
@app.route('/ao/housing')
def ao_housing():
    if not require_login('AO'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT a.id, a.block, a.flat_number, a.type, a.occupied,
               p.fullname
        FROM accommodations a
        LEFT JOIN personnel p ON a.occupant_id = p.id
    """)

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "id": d[0],
            "block": d[1],
            "flat": d[2],
            "type": d[3],
            "occupied": d[4],
            "occupant": d[5] if d[5] else "Vacant"
        }
        for d in data
    ])

@app.route('/ao/mark-occupied/<int:id>', methods=['POST'])
def mark_occupied(id):
    if not require_login('AO'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE accommodations
        SET occupied = TRUE
        WHERE id = %s
    """, (id,))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "Marked as occupied"})

@app.route('/ao/assign', methods=['POST'])
def ao_assign():

    data = request.get_json()

    conn = get_connection()
    cur = conn.cursor()

    try:

        # ================= ASSIGN HOUSE =================

        cur.execute("""
            UPDATE accommodations
            SET occupied = TRUE,
                occupant_id = %s
            WHERE id = %s
            AND occupied = FALSE
            RETURNING id
        """, (data['personnel_id'], data['accommodation_id']))

        result = cur.fetchone()

        if not result:

            conn.rollback()

            return jsonify({
                "error": "House already occupied or invalid"
            }), 400


        # ================= UPDATE APPLICATION =================

        cur.execute("""
            UPDATE applications
            SET status = 'assigned'
            WHERE personnel_id = %s
            AND status = 'pending'
        """, (data['personnel_id'],))


        # ================= GET PERSONNEL DETAILS =================

        cur.execute("""
            SELECT fullname, email
            FROM personnel
            WHERE id = %s
        """, (data['personnel_id'],))

        personnel = cur.fetchone()


        # ================= GET HOUSE DETAILS =================

        cur.execute("""
            SELECT block, flat_number
            FROM accommodations
            WHERE id = %s
        """, (data['accommodation_id'],))

        house = cur.fetchone()


        # ================= COMMIT DATABASE =================

        conn.commit()


        # ================= SEND EMAIL =================

        if personnel and house:

            fullname = personnel[0]
            email = personnel[1]

            block = house[0]
            flat_number = house[1]

            send_email(

                email,

                "Accommodation Approved",

                f"""
Dear {fullname},

Your accommodation application has been APPROVED.

Assigned Accommodation:

Block: {block}
Flat Number: {flat_number}

Please log into the accommodation portal for more details.

NAF Base Kano Accommodation System
"""
            )


        return jsonify({
            "message": "Assigned successfully"
        })


    except Exception as e:

        conn.rollback()

        print("AO ASSIGN ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500


    finally:

        cur.close()
        conn.close()

@app.route('/personnel/allocation')
def personnel_allocation():
    if 'user_id' not in session:
        return jsonify({"message": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT block, flat_number
        FROM accommodations
        WHERE occupant_id = %s
        LIMIT 1
    """, (session['user_id'],))

    data = cur.fetchone()

    cur.close()
    conn.close()

    if not data:
     return jsonify({"block": None, "flat": None})

    return jsonify({
        "block": data[0],
        "flat": data[1]
    })

@app.route('/ao/checkout/<int:accommodation_id>', methods=['POST'])
def ao_checkout(accommodation_id):
    if not require_login('AO'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE accommodations
        SET occupied = FALSE,
            occupant_id = NULL
        WHERE id = %s
    """, (accommodation_id,))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"message": "Checked out successfully"})




@app.route('/ao/approve/<int:id>', methods=['POST'])
def ao_approve(id):
    conn = get_connection()
    cur = conn.cursor()

    # get user email
    cur.execute("""
        SELECT p.email, p.fullname
        FROM applications a
        JOIN personnel p ON a.personnel_id = p.id
        WHERE a.id = %s
    """, (id,))
    user = cur.fetchone()

    # approve
    cur.execute("UPDATE applications SET status='approved' WHERE id=%s", (id,))
    conn.commit()

    cur.close()
    conn.close()

    # send email
    if user:
        send_email(
            user[0],
            "Accommodation Assigned",
            f"Dear {user[1]},\n\nYour accommodation request has been approved.\n\nThank you."
            
        )

    return jsonify({"message": "Application approved"})


@app.route('/ao/reject/<int:id>', methods=['POST'])
def ao_reject(id):

    conn = get_connection()
    cur = conn.cursor()

    try:

        # ================= GET USER DETAILS =================

        cur.execute("""
            SELECT p.email, p.fullname

            FROM applications a

            JOIN personnel p
            ON a.personnel_id = p.id

            WHERE a.id = %s
        """, (id,))

        user = cur.fetchone()


        # ================= REJECT APPLICATION =================

        cur.execute("""
            UPDATE applications
            SET status = 'rejected'
            WHERE id = %s
        """, (id,))


        # ================= SAVE =================

        conn.commit()


        # ================= SEND EMAIL =================

        if user:

            email = user[0]
            fullname = user[1]

            send_email(

                email,

                "Accommodation Application Rejected",

                f"""
Dear {fullname},

Your accommodation application has been REJECTED.

Please contact the Accommodation Office for clarification if necessary.

NAF Base Kano Accommodation System
"""
            )


        return jsonify({
            "message": "Application rejected successfully"
        })


    except Exception as e:

        conn.rollback()

        print("AO REJECT ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500


    finally:

        cur.close()
        conn.close()


# AO complaints
@app.route('/ao/complaints')
def ao_complaints():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT c.id, p.fullname, p.service_number,
               a.block, a.flat_number, c.message
        FROM complaints c
        JOIN personnel p ON c.personnel_id = p.id
        LEFT JOIN accommodations a ON a.occupant_id = p.id
        WHERE c.stage = 'ao'
    """)

    data = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "id": d[0],
            "name": d[1],
            "service_number": d[2],
            "block": d[3],
            "flat": d[4],
            "message": d[5]
        }
        for d in data
    ])


@app.route('/ao/forward/<int:id>', methods=['POST'])
def ao_forward(id):
    if not require_login('AO'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    # check current stage
    cur.execute("SELECT stage FROM complaints WHERE id=%s", (id,))
    before = cur.fetchone()

    # update stage
    cur.execute("""
        UPDATE complaints
        SET stage='commander'
        WHERE id=%s
    """, (id,))

    conn.commit()

    # confirm update
    cur.execute("SELECT stage FROM complaints WHERE id=%s", (id,))
    after = cur.fetchone()

    cur.close()
    conn.close()

    return jsonify({
        "message": "Forwarded to Commander",
        "before": before,
        "after": after
    })


@app.route('/ao/history')
def ao_history():

    if not require_login('AO'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            p.fullname,
            p.service_number,
            a.block,
            a.flat_number,
            ap.status,
            ap.created_at

        FROM applications ap

        JOIN personnel p 
            ON ap.personnel_id = p.id

        LEFT JOIN accommodations a 
            ON a.occupant_id = p.id

        ORDER BY ap.created_at DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "name": r[0],
            "service_number": r[1],
            "block": r[2] or "-",
            "flat": r[3] or "-",
            "status": r[4],
            "date": str(r[5])
        }
        for r in rows
    ])
@app.route('/ao/decisions')
def ao_decisions():

    if not require_login('AO'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            p.fullname,
            p.service_number,
            a.block,
            a.flat_number,
            c.message,
            c.status

        FROM complaints c

        JOIN personnel p
            ON c.personnel_id = p.id

        LEFT JOIN accommodations a
            ON a.occupant_id = p.id

        WHERE c.status IN ('approved', 'rejected')

        ORDER BY c.id DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "name": r[0],
            "service_number": r[1],
            "block": r[2] or "-",
            "flat_number": r[3] or "-",
            "message": r[4],
            "status": r[5]
        }
        for r in rows
    ])
@app.route('/ao/clear-history', methods=['POST'])
def clear_ao_history():

    if not require_login('AO'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    # delete only processed applications
    cur.execute("""
        DELETE FROM applications
        WHERE status IN ('approved', 'rejected', 'assigned')
    """)

    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "message": "History cleared successfully"
    })
# ================= COMMANDER =================

def require_login(role=None):
    if 'role' not in session:
        return False

    if role:
        return session.get('role').lower() == role.lower()

    return True

@app.route('/commander/overview')
def commander_overview():
    conn = get_connection()
    cur = conn.cursor()

    # total personnel
    cur.execute("SELECT COUNT(*) FROM personnel")
    total_personnel = cur.fetchone()[0]

    # occupied spaces
    cur.execute("SELECT COUNT(*) FROM accommodations WHERE occupied = TRUE")
    occupied = cur.fetchone()[0]

    # available spaces
    cur.execute("SELECT COUNT(*) FROM accommodations WHERE occupied = FALSE")
    available = cur.fetchone()[0]

    cur.close()
    conn.close()

    return jsonify({
        "total_personnel": total_personnel,
        "occupied": occupied,
        "available": available
    })
@app.route('/commander/allocations')
def commander_allocations():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            p.fullname,
            p.service_number,
            a.block,
            a.flat_number,
            a.occupied
        FROM accommodations a
        JOIN personnel p ON a.occupant_id = p.id
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "name": r[0],
            "service_number": r[1],
            "accommodation": f"{r[2]} - {r[3]}",
            "status": "Occupied" if r[4] else "Vacant"
        }
        for r in rows
    ])

@app.route('/commander/complaints')
def commander_complaints():
    if not require_login('Commander'):
        return jsonify({"error": "Unauthorized"}), 403

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 
            c.id,
            p.fullname,
            p.service_number,
            a.block,
            a.flat_number,
            c.message,
            c.status,
            c.stage
        FROM complaints c
        JOIN personnel p ON c.personnel_id = p.id
        LEFT JOIN accommodations a ON a.occupant_id = p.id
        WHERE c.stage = 'commander'
        ORDER BY c.id DESC
    """)

    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify([
        {
            "id": r[0],
            "name": r[1],
            "service_number": r[2],
            "block": r[3] or "-",
            "flat": r[4] or "-",
            "message": r[5],
            "status": r[6],
            "stage": r[7]
        }
        for r in rows
    ])


@app.route('/commander/approve/<int:id>', methods=['POST'])
def commander_approve(id):

    conn = get_connection()
    cur = conn.cursor()

    try:

        # ================= FETCH USER + LOCATION =================

        cur.execute("""
            SELECT p.email,
                   p.fullname,
                   p.service_number,
                   a.block,
                   a.flat_number
            FROM complaints c
            JOIN personnel p ON c.personnel_id = p.id
            LEFT JOIN accommodations a ON a.occupant_id = p.id
            WHERE c.id = %s
        """, (id,))

        user = cur.fetchone()


        # ================= UPDATE COMPLAINT =================

        cur.execute("""
            UPDATE complaints
            SET status = 'approved',
                stage = 'resolved'
            WHERE id = %s
        """, (id,))


        conn.commit()


        # ================= SEND EMAIL =================

        if user:

            email = user[0]
            fullname = user[1]
            service_number = user[2]
            block = user[3] or "N/A"
            flat_number = user[4] or "N/A"

            send_email(

                email,

                "Maintenance Request Approved",

                f"""
Dear {fullname} ({service_number}),

Your maintenance complaint has been APPROVED by the Commander.

Location:
Block: {block}
Flat Number: {flat_number}

Your request has been forwarded for action.

NAF Base Kano Accommodation System
"""
            )


        return jsonify({
            "message": "Maintenance approved"
        })


    except Exception as e:

        conn.rollback()

        print("COMMANDER APPROVE ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500


    finally:

        cur.close()
        conn.close()


@app.route('/commander/reject/<int:id>', methods=['POST'])
def commander_reject(id):

    conn = get_connection()
    cur = conn.cursor()

    try:

        # ================= FETCH USER + LOCATION =================

        cur.execute("""
            SELECT p.email,
                   p.fullname,
                   p.service_number,
                   a.block,
                   a.flat_number
            FROM complaints c
            JOIN personnel p ON c.personnel_id = p.id
            LEFT JOIN accommodations a ON a.occupant_id = p.id
            WHERE c.id = %s
        """, (id,))

        user = cur.fetchone()


        # ================= UPDATE COMPLAINT =================

        cur.execute("""
            UPDATE complaints
            SET status = 'rejected',
                stage = 'resolved'
            WHERE id = %s
        """, (id,))


        conn.commit()


        # ================= SEND EMAIL =================

        if user:

            email = user[0]
            fullname = user[1]
            service_number = user[2]
            block = user[3] or "N/A"
            flat_number = user[4] or "N/A"

            send_email(

                email,

                "Maintenance Request Rejected",

                f"""
Dear {fullname} ({service_number}),

Your maintenance complaint was NOT approved by the Commander.

Location:
Block: {block}
Flat Number: {flat_number}

Please contact the Accommodation Office for clarification if necessary.

NAF Base Kano Accommodation System
"""
            )


        return jsonify({
            "message": "Maintenance rejected"
        })


    except Exception as e:

        conn.rollback()

        print("COMMANDER REJECT ERROR:", e)

        return jsonify({
            "error": str(e)
        }), 500


    finally:

        cur.close()
        conn.close()


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')
# ================= RUN =================

if __name__ == "__main__":
    app.run(debug=True)