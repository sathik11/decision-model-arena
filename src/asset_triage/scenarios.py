"""Sample payloads for the two demo use cases."""

INCIDENT_SAMPLE = {
    "asset_id": "ASSET-042",
    "asset_type": "rotating equipment",
    "location": "North processing area",
    "report": (
        "Operator heard a new metallic grinding noise. Vibration increased rapidly "
        "and a hot bearing smell was noticed. No visible leak or injury."
    ),
    "sensor_summary": {
        "vibration": "12.8 mm/s, above trip advisory",
        "bearing_temperature": "94 C and rising",
        "power_draw": "11% above normal",
    },
    "recent_work": [
        "Bearing lubrication completed 9 days ago",
        "Coupling alignment inspection deferred at last service",
    ],
}

FIREWALL_SAMPLE = {
    "task": (
        "The overnight shift asks: is ASSET-042 safe to keep running until the "
        "planned Friday outage, or must it be stopped now?"
    ),
    "items": [
        "Operator report 03:14 — new metallic grinding noise from the drive end.",
        "Vibration trend: 4.1 mm/s baseline, now 12.8 mm/s over 40 minutes.",
        "Bearing temperature 94 C and still climbing at roughly 1.5 C per hour.",
        "Asset nameplate: 400 kW, installed 2014, duty class continuous.",
        "Canteen menu for Thursday has been updated on the intranet.",
        "Work order WO-88213 closed: bearing lubrication completed 9 days ago.",
        "Coupling alignment inspection deferred at the last service window.",
        "Shift handover note: night crew reported nothing unusual at 22:00.",
        "Site parking permit renewals are due at the end of the month.",
        "Historian: identical vibration signature preceded a 2019 bearing seizure.",
        "Spare bearing set 6316-C3 is in stock at the central store, bin B-14.",
        "HR reminder: annual leave requests close on the 30th.",
        "Planned outage is scheduled for Friday 06:00, 62 hours from now.",
        "Trip advisory threshold for this machine class is 11.2 mm/s.",
        "IT notice: VPN maintenance on Sunday between 01:00 and 03:00.",
        "No lubrication leak, smoke, or personnel exposure has been observed.",
    ],
}
