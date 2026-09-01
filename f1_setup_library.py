"""Normalized F1 26 setup baselines from the user-supplied Matt212 PDF."""

SOURCE = "Matt212 Setups.pdf - F1 26 dry setup sheet"

# Values: aero, transmission, geometry, suspension, brakes, tyres,
# PDF 50% strategy, 50% race laps, approximate fresh-tyre lap, pit loss.
_RAW = {
    "Australia": ((21,17),(100,25),(-3.40,-1.90,.02,.13),(34,9,9,14,21,47),(55,100),(24.5,24.5,22.0,22.0),"M - H | pit L12-13",29,78.0,21),
    "China": ((35,28),(100,25),(-3.40,-1.90,.03,.13),(34,11,9,15,22,49),(56,99),(25.4,26.9,21.9,22.6),"M - H | pit L12; alternate M-H-M",28,92.0,23),
    "Japan": ((24,16),(100,25),(-3.40,-1.90,.01,.12),(38,5,7,14,21,48),(56,99),(27.9,27.9,22.0,22.0),"M - H | pit L12",27,88.0,22),
    "Bahrain": ((24,18),(100,25),(-3.40,-1.90,.03,.13),(32,10,5,15,22,49),(56,99),(25.0,25.0,21.9,21.9),"M - H | pit L12",29,92.0,22),
    "Saudi Arabia": ((16,10),(100,30),(-3.40,-1.90,.03,.13),(36,13,5,13,22,49),(56,99),(24.3,24.3,22.3,22.3),"M - H | pit L11-12",25,88.0,23),
    "Miami": ((25,20),(100,20),(-3.40,-1.90,.01,.12),(38,4,6,14,21,48),(56,99),(26.0,26.0,22.7,22.7),"M - H | pit L12-13",29,90.0,22),
    "Canada": ((28,20),(100,25),(-3.40,-1.90,.01,.12),(36,4,4,11,22,49),(56,99),(24.0,24.0,23.3,23.3),"M - H | pit L15; alternate M-H-M L10/L25",35,72.0,20),
    "Monaco": ((50,50),(100,20),(-3.40,-1.90,.01,.12),(39,4,4,12,22,50),(56,99),(28.5,28.5,22.0,22.0),"M - H | pit with wing damage",39,72.0,19),
    "Barcelona": ((46,36),(100,30),(-3.40,-1.90,.01,.12),(39,15,14,12,22,49),(56,99),(26.3,28.2,21.5,22.8),"M - H | pit L14-15",33,78.0,22),
    "Austria": ((26,18),(100,30),(-3.40,-1.90,.01,.12),(38,17,11,15,22,49),(56,99),(24.0,24.0,23.0,23.0),"M - H | pit L16",36,65.0,20),
    "Britain": ((17,10),(100,25),(-3.40,-1.90,.01,.12),(38,5,4,12,22,49),(56,99),(29.5,29.5,23.4,23.4),"M - H | pit L12",26,87.0,23),
    "Belgium": ((9,0),(100,20),(-3.40,-1.90,.06,.12),(38,4,4,19,24,50),(56,99),(23.5,23.5,21.8,21.8),"M - H | pit L10",22,105.0,24),
    "Hungary": ((49,46),(100,20),(-3.40,-1.90,.01,.11),(40,30,5,18,21,48),(56,99),(28.0,28.0,23.5,23.5),"M - H | pit L14-15",35,78.0,22),
    "Netherlands": ((48,42),(100,25),(-3.40,-1.90,.01,.12),(39,26,6,19,21,49),(56,99),(24.2,25.1,22.1,23.3),"M - H | pit L15-16",36,72.0,20),
    "Monza": ((9,0),(100,30),(-3.40,-1.90,.01,.11),(38,3,5,15,23,49),(56,99),(29.5,29.5,26.5,26.5),"M - H | pit L11-12",27,80.0,24),
    "Madrid": ((39,31),(100,25),(-3.40,-1.90,.01,.12),(37,4,5,12,23,51),(56,99),(28.3,28.3,21.9,21.9),"M - H | pit L10-11",29,85.0,22),
    "Azerbaijan": ((12,2),(100,20),(-3.40,-1.90,.01,.12),(36,16,5,12,22,48),(56,99),(24.3,24.3,21.5,21.5),"M - H | pit L11-12",26,102.0,24),
    "Singapore": ((50,49),(100,25),(-3.40,-1.90,.01,.11),(38,4,5,12,22,48),(56,99),(23.7,23.7,21.6,21.6),"M - H | pit L14",31,94.0,24),
    "Texas": ((46,36),(100,40),(-3.40,-1.90,.01,.11),(34,11,15,5,21,48),(56,99),(28.0,28.0,22.5,22.5),"M - H | pit L11-12",28,94.0,23),
    "Mexico": ((44,34),(100,30),(-3.40,-1.90,.01,.12),(35,14,7,10,23,49),(56,99),(24.2,24.2,22.1,22.1),"M - H | pit L15; alternate M-H-M L10/L25",36,79.0,22),
    "Brazil": ((35,25),(100,30),(-3.40,-1.90,.01,.12),(37,16,5,11,22,48),(56,99),(28.3,28.3,21.7,21.7),"M - H | pit L15-16",36,70.0,21),
    "Las Vegas": ((9,0),(100,20),(-3.40,-1.90,.01,.11),(37,8,7,8,23,48),(55,99),(24.7,24.7,22.5,22.5),"M - H | pit L11-12",25,93.0,25),
    "Qatar": ((45,35),(100,40),(-3.40,-1.90,.01,.12),(39,29,3,10,22,48),(56,99),(28.5,29.5,21.3,22.6),"M - H | pit L12-13",29,83.0,23),
    "Abu Dhabi": ((45,35),(100,20),(-3.40,-1.90,.01,.11),(37,13,16,4,21,48),(56,99),(27.5,27.5,22.0,22.0),"M - H | pit L12-13",29,90.0,22),
    "Imola": ((39,29),(100,20),(-3.40,-1.90,.01,.12),(38,20,3,11,22,49),(56,99),(27.5,27.5,24.5,24.5),"M - H | pit L14-15",32,76.0,22),
    "Austria Reverse": ((30,20),(100,30),(-3.40,-1.90,.01,.11),(36,14,16,7,23,50),(56,99),(24.7,24.7,22.0,22.0),"M - H | pit L14-15",36,67.0,20),
    "Britain Reverse": ((27,18),(100,30),(-3.40,-1.90,.01,.11),(37,4,6,17,21,50),(56,99),(28.1,28.1,22.5,22.5),"M - H - M | pit L8/L18",26,88.0,23),
    "Netherlands Reverse": ((50,41),(100,25),(-3.40,-1.90,.01,.11),(37,10,9,15,22,48),(56,99),(25.7,24.4,23.4,21.9),"M - H | pit L15-16",36,74.0,20),
}

ALIASES = {"Melbourne":"Australia", "Shanghai":"China", "Suzuka":"Japan",
    "Jeddah":"Saudi Arabia", "Montreal":"Canada", "Catalunya":"Barcelona",
    "Silverstone":"Britain", "Spa":"Belgium", "Hungaroring":"Hungary",
    "Zandvoort":"Netherlands", "Baku":"Azerbaijan", "COTA":"Texas",
    "Interlagos":"Brazil", "Losail":"Qatar", "Miami (USA)":"Miami",
    "Monza (Italy)":"Monza", "Barcelona (Spain)":"Barcelona",
    "Texas (USA)":"Texas", "Las Vegas (USA)":"Las Vegas", "Imola (Italy)":"Imola"}


def tracks():
    return tuple(_RAW)


def get_setup(track):
    name = ALIASES.get(track, track)
    raw = _RAW.get(name)
    if not raw:
        return None
    aero, transmission, geometry, suspension, brakes, tyres, strategy, laps, base, pit = raw
    return {"track": name, "source": SOURCE,
        "front_wing": aero[0], "rear_wing": aero[1],
        "on_throttle_diff": transmission[0], "off_throttle_diff": transmission[1],
        "front_camber": geometry[0], "rear_camber": geometry[1],
        "front_toe": geometry[2], "rear_toe": geometry[3],
        "front_suspension": suspension[0], "rear_suspension": suspension[1],
        "front_anti_roll_bar": suspension[2], "rear_anti_roll_bar": suspension[3],
        "front_ride_height": suspension[4], "rear_ride_height": suspension[5],
        "brake_bias": brakes[0], "brake_pressure": brakes[1],
        "front_left_pressure": tyres[0], "front_right_pressure": tyres[1],
        "rear_left_pressure": tyres[2], "rear_right_pressure": tyres[3],
        "pdf_strategy": strategy, "race_laps_50": laps,
        "baseline_lap_seconds": base, "pit_loss_seconds": pit}
