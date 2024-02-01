from flask import Flask, request, jsonify
import json
from dateutil.parser import parse
from flask_cors import CORS

app = Flask(__name__)
cors = CORS(app, resources={r"/process": {"origins": "http://localhost:3000"}})


def events_are_same_type(new_entry, row):
    """check if both events are admit or both are discharge"""
    return (new_entry["EVENT_TYPE"] == "Discharge" and row["EncounterEndTime"]) or (
        new_entry["EVENT_TYPE"] == "Admission" and row["EncounterBeginTime"]
    )


def matching_patient_visit(new_entry, row):
    """match patient visit on identifier and facility. not including encounter class here based on caveats in prompt"""
    return (
        row["PatientIdentifier"] == new_entry["PATIENT_IDENTIFIER"]
        and row["Facility"] == new_entry["FACILITY"]
    )


def calculate_encounter_length(begin_time, end_time):
    """calculate the length of the encounter"""
    if begin_time and end_time:
        parsed_end_time = parse(end_time)
        parsed_begin_time = parse(begin_time)
        if parsed_end_time < parsed_begin_time:
            return -1
        return parsed_end_time - parsed_begin_time
    return None


def format_data_for_new_row(new_entry):
    """this encounter does not yet exist in our formatted list, format it to be added as a new row"""
    encounter_begin_time = (new_entry["EVENT_TIME"] if new_entry["EVENT_TYPE"] == "Admission" else None)
    encounter_end_time = (new_entry["EVENT_TIME"] if new_entry["EVENT_TYPE"] == "Discharge" else None)

    # although in the example it says 'Length of Stay' I'm updating that column header to LengthOfStay for consistency
    return {
        "PatientIdentifier": new_entry["PATIENT_IDENTIFIER"],
        "Facility": new_entry["FACILITY"],
        "PatientComplaint": new_entry["PATIENT_COMPLAINT"],
        "EncounterClass": new_entry["PATIENT_CLASS"],
        "EncounterBeginTime": encounter_begin_time,
        "EncounterEndTime": encounter_end_time,
        "LengthOfStay": None,
    }


def update_row_data(new_entry, row):
    """add additional data to existent encounter. encounter class of discharge event overrides encounter class of admit event"""
    updated_row = row
    if new_entry["EVENT_TYPE"] == "Discharge":
        length_of_stay = calculate_encounter_length(
            row["EncounterBeginTime"], new_entry["EVENT_TIME"]
        )
        if length_of_stay == -1:
            # the discharge date is before the admit date, these should be separated entries.
            return -1
        updated_row["LengthOfStay"] = length_of_stay
        updated_row["EncounterClass"] = new_entry["PATIENT_CLASS"]
        updated_row["EncounterEndTime"] = new_entry["EVENT_TIME"]
    else:
        # assuming that there will always be a value of either Admission or Discharge in the event type column.
        length_of_stay = calculate_encounter_length(
            new_entry["EVENT_TIME"], row["EncounterEndTime"]
        )
        if length_of_stay == -1:
            return -1
        updated_row["EncounterBeginTime"] = new_entry["EVENT_TIME"]
        updated_row["LengthOfStay"] = length_of_stay

    return updated_row

    # it's noted in caveats that a patient may have two admit events for the same stay, but it's not indicated how it should be handled. I am opting to count that as a separate event, rather than risk consolidating events that should not be consolidated.


@app.route("/process", methods=["POST"])
def process_data():
    try:
        incoming_data = request.json["elements"]
        formatted_data = []
        for new_entry in incoming_data:
            match_found = False
            for index, row in enumerate(formatted_data):
                if matching_patient_visit(new_entry, row) and not events_are_same_type(new_entry, row):
                    match_found = True
                    new_row = update_row_data(new_entry, row)
                    if new_row == -1:
                        # this is only used when the discharge date is before the admit date
                        formatted_data.append(format_data_for_new_row(new_entry))
                    else:
                        formatted_data[index] = new_row
                    break
            if not match_found:
                # add the new_entry in the incoming data as a new row in the formatted data
                formatted_data.append(format_data_for_new_row(new_entry))

        # set the default to string since we have timedelta data
        return json.dumps({"elements": formatted_data}, default=str), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
