import datetime
import mysql.connector


def resource_fetch(request_id: int) -> dict:
    """
    Track resources based on location for a single disaster request ID.
    Returns nearby resource centers (within 10 km).
    """
    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="survivorsync"
        )
        cursor = conn.cursor(dictionary=True)

        # Get the disaster request
        cursor.execute("SELECT * FROM disaster_requests WHERE id = %s", (request_id,))
        disaster = cursor.fetchone()

        if not disaster:
            return {
                "error": f"No disaster request found with ID {request_id}",
                "results": {}
            }

        lat = disaster.get("latitude")
        lon = disaster.get("longitude")

        if lat is None or lon is None:
            return {
                "disaster": disaster,
                "resources": [],
                "error": "Missing latitude or longitude for disaster request"
            }

        # Find nearby resource centers within 10km
        # Find nearby resource centers within 10km (uses correct column names)
        resource_query = """
            SELECT *, 
            ST_Distance_Sphere(POINT(`long`, `lat`), POINT(%s, %s)) AS distance
            FROM resource_centers
            WHERE ST_Distance_Sphere(POINT(`long`, `lat`), POINT(%s, %s)) <= 10000
        """
        cursor.execute(resource_query, (lon, lat, lon, lat))
        resources = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "resources": resources,
            "status": "success",
            "message": f"Found {len(resources)} resource center(s) near disaster ID {request_id}"
        }

    except mysql.connector.Error as err:
        return {
            "error": str(err),
            "results": {}
        }
    except Exception as e:
        return {
            "error": str(e),
            "results": {}
        }
    

def requests_fetch(location: list[float], disaster_id: int) -> dict:
    print(f"Fetching requests for disaster ID {disaster_id} near coordinates {location}")
    try:
        
        lat, long = location if len(location) == 2 else (0.0, 0.0)
        print(f"Fetching requests for disaster ID {disaster_id} near coordinates ({lat}, {long})...")
        now = datetime.datetime.now()
        today_start = datetime.datetime.combine(now.date(), datetime.time.min)
        tomorrow_start = today_start + datetime.timedelta(days=1)
        print(f"Today's date: {today_start}, Tomorrow's date: {tomorrow_start}")

        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="survivorsync"
        )
        cursor = conn.cursor(dictionary=True)

        query = """
            SELECT * FROM disaster_requests
            WHERE disasterId = %s
            AND created_at >= %s AND created_at < %s
            AND ST_Distance_Sphere(
                POINT(longitude, latitude),
                POINT(%s, %s)
            ) <= 10000
            """

        cursor.execute(query, (disaster_id, today_start, tomorrow_start, long, lat))
        disaster_data = cursor.fetchall()

        cursor.close()
        conn.close()

        return {
            "disaster_data": disaster_data,
            "message": f"Found {len(disaster_data)} requests for disaster ID {disaster_id} near coordinates ({lat}, {long}) on {now.date()}."
        }
    except mysql.connector.Error as err:
        print(f"Database error: {err}")
        return {
            "error": f"Database error: {err}"
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            "error": f"Unexpected error: {e}"
        }


def update_request_status(request_id: int, status: str):

    # Only handle 'verified' status
    if status.lower() != "verified":
        print("Status is not 'verified', no update performed.")
        return False

    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="survivorsync"
        )

        cursor = conn.cursor(dictionary=True)       

        # Update query
        query = "UPDATE disaster_requests SET isVerified = %s WHERE id = %s"
        cursor.execute(query, (True, request_id))
        conn.commit()

        if cursor.rowcount > 0:
            print(f"Request ID {request_id} updated successfully to verified.")
            return True
        else:
            print(f"No request found with ID {request_id}.")
            return False

    except mysql.connector.Error as err:
        print(f"Database error: {err}")
        return {
            "error": str(err),
            "results": {}
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            "error": str(e),
            "results": {}
        }



# To assign the resources for the request
def assign_resources(request_id: int, resource_center_ids: list[int], quantities: list[int]) -> dict:
    """
    Assigns resources from multiple resource centers to a disaster request.
    """
    try:
        print(f"Assigning resources to request ID {request_id}...")

        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="survivorsync"
        )

        cursor = conn.cursor(dictionary=True)

        # Check disaster request exists
        cursor.execute("SELECT * FROM disaster_requests WHERE id = %s", (request_id,))
        disaster = cursor.fetchone()
        if not disaster:
            return {
                "error": f"Disaster request with ID {request_id} not found.",
                "results": {}
            }

        # Allocation process
        allocations = []
        for resource_center_id, amount in zip(resource_center_ids, quantities):
            # Insert into allocated_resources
            insert_query = """
                INSERT INTO allocated_resources (disasterRequestId, resourceCenterId, amount, isAllocated)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(insert_query, (request_id, resource_center_id, amount, True))
            allocations.append({
                "disasterRequestId": request_id,
                "resourceCenterId": resource_center_id,
                "amount": amount,
                "isAllocated": True
            })

        conn.commit()
        cursor.close()
        conn.close()

        return {
            "results": allocations,
            "status": "success",
            "message": f"{len(allocations)} resource(s) successfully allocated to disaster request {request_id}."
        }

    except mysql.connector.Error as err:
        print(f"Database error: {err}")
        return {
            "error": str(err),
            "results": {}
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            "error": str(e),
            "results": {}
        }

   

def change_status_after_assign_resources(request_id: int, status: str) -> dict:
    """
    Change the status of a disaster request.
    """
    try:
        print(f"Changing status of request ID {request_id} to '{status}'...")

        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="survivorsync"
        )
        cursor = conn.cursor(dictionary=True)

        # Update the disaster request status
        if status.lower() != "success":
            return {
                "error": f"Invalid status '{status}'. Only 'success' allocations are allowed.",
                "results": {}
            }
        update_query = "UPDATE disaster_requests SET status = 'IN_PROGRESS' WHERE id = %s"
        cursor.execute(update_query, (request_id,))
        conn.commit()

        cursor.close()
        conn.close()

        return {
            "status": "IN_PROGRESS",
            "message": f"Status of disaster request {request_id} changed to '{status}'."
        }

    except mysql.connector.Error as err:
        print(f"Database error: {err}")
        return {
            "error": str(err),
            "results": {}
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            "error": str(e),
            "results": {}
        }