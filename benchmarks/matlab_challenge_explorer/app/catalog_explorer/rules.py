"""Deterministic classification rules (keyword / section analysis).

Every rule table is plain data at the top of this module and is documented in
README.md ("Extraction rules").  Nothing here knows about individual projects.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from .parser import clean_inline, strip_urls

PROJECT_TYPES = [
    "Modeling & Simulation", "AI / Machine Learning", "Control Design", "Signal Processing",
    "Optimization", "Data Analysis", "Embedded / Real-Time", "Hardware Integration",
    "System Design", "App / UI Development", "Verification / Testing",
]
APPLICATION_AREAS = [
    "Energy / Sustainability", "Automotive", "Aerospace", "Robotics / Automation",
    "Manufacturing / Industry 4.0", "Communications / Wireless", "Smart Infrastructure / IoT",
    "Healthcare / Medical", "Education / Research", "Finance / Economics",
]
DIFFICULTIES = ["Beginner", "Intermediate", "Advanced"]
HARDWARE_REQUIRED = ["None", "Optional", "Required"]

# --------------------------------------------------------------------------- products
# (canonical name, name regex, product-page slugs, help doc roots)
_PRODUCT_ROWS: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    ("Deep Learning Toolbox", r"Deep Learning Toolbox", ("deep-learning",), ("deeplearning",)),
    ("Statistics and Machine Learning Toolbox",
     r"Statistics and Machine Learning Toolbox|Machine Learning Toolbox|Statistics Toolbox", ("statistics",), ("stats",)),
    ("Computer Vision Toolbox", r"Computer Vision (?:System )?Toolbox", ("computer-vision",), ("vision",)),
    ("Image Processing Toolbox", r"Image Processing Toolbox", ("image-processing", "image"), ("images",)),
    ("Optimization Toolbox", r"Optimization Toolbox", ("optimization",), ("optim",)),
    ("Global Optimization Toolbox", r"Global Optimization Toolbox", ("global-optimization",), ("gads",)),
    ("UAV Toolbox", r"UAV Toolbox", ("uav",), ("uav",)),
    ("Navigation Toolbox", r"Navigation Toolbox", ("navigation",), ("nav",)),
    ("Sensor Fusion and Tracking Toolbox", r"Sensor Fusion and Tracking Toolbox|Tracking Toolbox",
     ("sensor-fusion-and-tracking",), ("fusion",)),
    ("Automated Driving Toolbox", r"Automated Driving Toolbox", ("automated-driving",), ("driving",)),
    ("Robotics System Toolbox", r"Robotics System Toolbox", ("robotics",), ("robotics",)),
    ("ROS Toolbox", r"ROS Toolbox", ("ros",), ("ros",)),
    ("Embedded Coder", r"Embedded Coder", ("embedded-coder",), ("ecoder",)),
    ("MATLAB Coder", r"MATLAB Coder", ("matlab-coder",), ("coder",)),
    ("Simulink Coder", r"Simulink Coder", ("simulink-coder",), ("rtw",)),
    ("GPU Coder", r"GPU Coder", ("gpu-coder",), ("gpucoder",)),
    ("HDL Coder", r"HDL Coder", ("hdl-coder",), ("hdlcoder",)),
    ("HDL Verifier", r"HDL Verifier", ("hdl-verifier",), ("hdlverifier",)),
    ("Fixed-Point Designer", r"Fixed-Point Designer", ("fixed-point-designer",), ("fixedpoint",)),
    ("Stateflow", r"Stateflow", ("stateflow",), ("stateflow",)),
    ("Simscape", r"Simscape(?!\s+(?:Electrical|Multibody|Fluids|Battery|Driveline))", ("simscape",), ("physmod", "simscape")),
    ("Simscape Electrical", r"Simscape Electrical|SimPowerSystems", (), ("sps",)),
    ("Simscape Multibody", r"Simscape Multibody|SimMechanics", ("simscape-multibody", "simmechanics"), ("sm",)),
    ("Simscape Fluids", r"Simscape Fluids", ("simscape-fluids",), ("hydro",)),
    ("Simscape Battery", r"Simscape Battery", ("simscape-battery",), ("simscape-battery",)),
    ("Simscape Driveline", r"Simscape Driveline", ("simscape-driveline",), ("sdl",)),
    ("Signal Processing Toolbox", r"Signal Processing Toolbox", ("signal",), ("signal",)),
    ("DSP System Toolbox", r"DSP System Toolbox", ("dsp-system",), ("dsp",)),
    ("Audio Toolbox", r"Audio Toolbox", ("audio",), ("audio",)),
    ("Communications Toolbox", r"Communications? Toolbox", ("communications",), ("comm",)),
    ("Antenna Toolbox", r"Antenna Toolbox", ("antenna",), ("antenna",)),
    ("Phased Array System Toolbox", r"Phased Array System Toolbox", ("phased-array",), ("phased",)),
    ("Radar Toolbox", r"Radar Toolbox", ("radar",), ("radar",)),
    ("Lidar Toolbox", r"Lidar Toolbox", ("lidar",), ("lidar",)),
    ("RF Toolbox", r"RF Toolbox", ("rf",), ("rf",)),
    ("Mapping Toolbox", r"Mapping Toolbox", ("mapping",), ("map",)),
    ("Reinforcement Learning Toolbox", r"Reinforcement Learning Toolbox", ("reinforcement-learning",), ("reinforcement-learning",)),
    ("Predictive Maintenance Toolbox", r"Predictive Maintenance Toolbox", ("predictive-maintenance",), ("predmaint",)),
    ("Text Analytics Toolbox", r"Text Analytics? Toolbox", ("text-analytics",), ("textanalytics",)),
    ("Econometrics Toolbox", r"Econometrics? Toolbox", ("econometrics",), ("econ",)),
    ("Financial Toolbox", r"Financial Toolbox", ("finance",), ("finance",)),
    ("Datafeed Toolbox", r"Datafeed Toolbox", ("datafeed",), ("datafeed",)),
    ("Database Toolbox", r"Database Toolbox", ("database",), ("database",)),
    ("Curve Fitting Toolbox", r"Curve Fitting Toolbox", ("curvefitting",), ("curvefit",)),
    ("Control System Toolbox", r"Control Systems? Toolbox", ("control",), ("control",)),
    ("Model Predictive Control Toolbox", r"Model[- ]Predictive Control Toolbox", ("model-predictive-control",), ("mpc",)),
    ("Robust Control Toolbox", r"Robust Control Toolbox", ("robust",), ("robust",)),
    ("Simulink Control Design", r"Simulink Control Design", (), ("slcontrol",)),
    ("Simulink Design Optimization", r"Simulink Design Optimization", ("sl-design-optimization",), ("sldo",)),
    ("Simulink Test", r"(?-i:Simulink Test)", ("simulink-test",), ("sltest",)),
    ("Simulink Coverage", r"(?-i:Simulink Coverage)", (), ("slcoverage",)),
    ("Requirements Toolbox", r"Requirements Toolbox|(?-i:Simulink Requirements)", ("requirements-toolbox",), ("slrequirements",)),
    ("Simulink 3D Animation", r"Simulink 3D Animation", ("3d-animation",), ("sl3d",)),
    ("Simulink Real-Time", r"Simulink Real-Time", ("simulink-real-time",), ("slrealtime",)),
    ("Simulink Design Verifier", r"Simulink Design Verifier", (), ("sldv",)),
    ("System Composer", r"System Composer", ("system-composer",), ("systemcomposer",)),
    ("RoadRunner", r"RoadRunner", ("roadrunner",), ("roadrunner",)),
    ("Powertrain Blockset", r"Powertrain Blockset", ("powertrain",), ("autoblks",)),
    ("Vehicle Dynamics Blockset", r"Vehicle Dynamics Blockset", ("vehicle-dynamics",), ("vdynblks",)),
    ("Aerospace Blockset", r"Aerospace Blockset", ("aerospace-blockset",), ("aeroblks",)),
    ("Aerospace Toolbox", r"Aerospace Toolbox", ("aerospace-toolbox",), ("aerotbx",)),
    ("Motor Control Blockset", r"Motor Control Blockset", ("motor-control",), ("mcb",)),
    ("Mixed-Signal Blockset", r"Mixed-Signal Blockset", (), ("msblks",)),
    ("SerDes Toolbox", r"SerDes Toolbox", ("serdes",), ("serdes",)),
    ("Vision HDL Toolbox", r"Vision HDL Toolbox", ("vision-hdl",), ("visionhdl",)),
    ("Deep Learning HDL Toolbox", r"Deep Learning HDL Toolbox", ("deep-learning-hdl",), ("deep-learning-hdl",)),
    ("Parallel Computing Toolbox", r"Parallel Computing Toolbox", ("parallel-computing",), ("parallel-computing",)),
    ("Polyspace", r"Polyspace", ("polyspace",), ("polyspace",)),
    ("SimBiology", r"SimBiology", ("simbiology",), ("simbio",)),
    ("Symbolic Math Toolbox", r"Symbolic Math Toolbox", (), ("symbolic",)),
    ("Medical Imaging Toolbox", r"Medical Imaging Toolbox", (), ("medical-imaging",)),
    ("Wavelet Toolbox", r"Wavelet Toolbox", ("wavelet",), ("wavelet",)),
    ("Ultrasound Toolbox", r"Ultrasound Toolbox", (), ("ultrasound",)),
    ("PDE Toolbox", r"PDE Toolbox", (), ("pde",)),
    ("Bioinformatics Toolbox", r"Bioinformatics Toolbox", (), ("bioinfo",)),
    ("Industrial Communication Toolbox", r"Industrial Communication Toolbox", ("industrial-communication",), ("icomm",)),
    ("Wireless Testbench", r"Wireless Testbench", ("wireless-testbench",), ("wireless-testbench",)),
    ("ThingSpeak", r"ThingSpeak", ("thingspeak",), ("thingspeak",)),
    ("MATLAB Mobile", r"MATLAB Mobile", ("matlab-mobile",), ()),
]

PRODUCTS: list[tuple[str, re.Pattern]] = [
    (name, re.compile(r"(?<![A-Za-z])(?:" + rx + r")(?![A-Za-z])", re.I)) for name, rx, _, _ in _PRODUCT_ROWS
]
SLUG_TO_PRODUCT = {slug: name for name, _, slugs, _ in _PRODUCT_ROWS for slug in slugs}
DOCROOT_TO_PRODUCT = {root: name for name, _, _, roots in _PRODUCT_ROWS for root in roots}

# Products that are part of the Simulink family (imply the Simulink platform).
SIMULINK_FAMILY = re.compile(r"^(Simscape|Simulink|Stateflow$|Powertrain|Vehicle Dynamics|Aerospace Blockset|"
                             r"Motor Control Blockset|Mixed-Signal|System Composer|HDL Coder|Requirements Toolbox)")


def detect_products(text: str, sections: dict[str, str]) -> list[str]:
    """Canonical product names found through names, product-page links and help links."""
    found: set[str] = set()
    for name, rx in PRODUCTS:
        if rx.search(text):
            found.add(name)
    for m in re.finditer(r"mathworks\.com/products/([a-z0-9-]+)", text, re.I):
        slug = m.group(1).lower()
        if slug in SLUG_TO_PRODUCT:
            found.add(SLUG_TO_PRODUCT[slug])
    for m in re.finditer(r"mathworks\.com/help/([a-z0-9_-]+)/", text, re.I):
        root = m.group(1).lower()
        if root in DOCROOT_TO_PRODUCT:
            found.add(DOCROOT_TO_PRODUCT[root])
    return sorted(found)


def detect_platforms(text: str, products: list[str]) -> list[str]:
    """MATLAB / Simulink: from prose mentions (URLs removed) and product families."""
    prose = strip_urls(text)
    simulink = bool(re.search(r"Simulink", prose, re.I)) or any(SIMULINK_FAMILY.match(p) for p in products)
    matlab = bool(re.search(r"MATLAB", prose, re.I)) or any(not SIMULINK_FAMILY.match(p) for p in products)
    if not simulink and not matlab:
        matlab = True
    return [p for p, on in (("MATLAB", matlab), ("Simulink", simulink)) if on]


# --------------------------------------------------------------------------- classification
# (label, regex, weight).  A label is assigned when its summed weight reaches TYPE_THRESHOLD.
# Fields scanned are weighted: title/summary/expertise x3, everything else x1 (see score()).
TYPE_THRESHOLD = 3
PROJECT_TYPE_RULES: dict[str, list[tuple[str, int]]] = {
    "Modeling & Simulation": [
        (r"\bmodel(?:l?ing|s)?\b|\bsimulat\w*|digital twin|\bsimscape\b|co-simulation|physics-based|plant model", 1),
        (r"modeling and simulation", 3)],
    "AI / Machine Learning": [
        (r"machine learning|deep learning|neural network|\bAI\b|artificial intelligence|reinforcement learning|"
         r"\bCNN\b|\bLSTM\b|classif\w+|large language model|\bLLM\b|transformer|natural language|generative|"
         r"\bYOLO\b|object detection|semantic segmentation|text analytics|\bNLP\b", 2)],
    "Control Design": [
        (r"\bcontrol(?:ler|lers)?\b|\bPID\b|\bMPC\b|model[- ]predictive|stabiliz\w+|disturbance rejection|"
         r"\bfeedback\b|trajectory tracking|fault[- ]tolerant|\bobserver\b|state estimation", 2)],
    "Signal Processing": [
        (r"signal processing|\bfilter(?:ing|s)?\b|spectrum|spectral|\bFFT\b|wavelet|\baudio\b|\bspeech\b|"
         r"\bradar\b|\bSAR\b|\bnoise\b|modulation|beamforming|image processing|time[- ]frequency|\bsignals?\b", 2)],
    "Optimization": [
        (r"optimi[sz]\w*|genetic algorithm|simulated annealing|linear programming|trade-?off|cost function|"
         r"minimi[sz]e|maximi[sz]e|path planning|trajectory planning", 2)],
    "Data Analysis": [
        (r"data analy\w+|big data|\bdataset\b|data-driven|statistic\w*|time[- ]series|forecast\w*|predict\w*|"
         r"data science|visuali[sz]\w+|feature extraction|regression|\bdata\b", 1)],
    "Embedded / Real-Time": [
        (r"embedded|real[- ]time|code generation|generate code|\bFPGA\b|\bHDL\b|\bPLC\b|firmware|microcontroller|"
         r"Cortex|\bGPU Coder\b|\bdeploy\w*|processor-in-the-loop|\bMCU\b|Jetson|Raspberry|low-cost hardware", 2)],
    "Hardware Integration": [
        (r"hardware|\bsensors?\b|\bactuators?\b|Raspberry Pi|Arduino|\bboard\b|software[- ]defined radio|\bSDR\b|"
         r"physical (?:robot|system)|\bdrone\b|\bIMU\b|hardware-in-the-loop|\bHIL\b|\bUSRP\b|\bPluto\b|Jetson|microcontroller", 1)],
    "System Design": [
        (r"system design|system-level|architecture|requirements|design automation|co-design|"
         r"\bintegrat\w+|system composer|system engineering|end-to-end|design (?:and|&) (?:implement|build)", 2)],
    "App / UI Development": [
        (r"App Designer|\bGUI\b|user interface|\bdashboard\b|interactive app|\bapp\b|web app|\bUI\b", 2)],
    "Verification / Testing": [
        (r"verification|validat\w+|\btest(?:ing|s)?\b|robustness|Simulink Test|fault injection|"
         r"fault detection|conformance|coverage|safety|scenario[- ]based|\bstress\b", 1)],
}

AREA_RULES: dict[str, list[tuple[str, int]]] = {
    "Energy / Sustainability": [
        (r"energy|renewable|sustainab\w+|battery|batteries|solar|\bwind\b|hydrogen|\bgrid\b|carbon|CO2|CO₂|"
         r"electrification|photovoltaic|climate|emission\w*|power system|power electronics|HVAC|heating|cooling|charging|"
         r"fuel cell|biofuel|net[- ]zero", 2)],
    "Automotive": [
        (r"automotive|vehicle|\bcar\b|\bcars\b|driving|\bEV\b|\bBEV\b|powertrain|autonomous|\bADAS\b|"
         r"traffic|engine|lane|race car|Formula Student", 2)],
    "Aerospace": [
        (r"aerospace|aircraft|\bUAV\b|\bUAM\b|drone|quadrotor|quadcopter|multirotor|minidrone|satellite|space|"
         r"flight|aerial|rocket|avionics|orbit\w*|air mobility|astronom\w+", 2)],
    "Robotics / Automation": [
        (r"robot\w*|manipulator|\bSLAM\b|odometry|automation|palletiz\w+|humanoid|quadruped|cobot|"
         r"mechatronic\w*|actuator|gripper|autonomous (?:navigation|systems?)|path planning", 2)],
    "Manufacturing / Industry 4.0": [
        (r"manufactur\w+|industry 4\.0|industrial|predictive maintenance|factory|production line|warehouse|"
         r"logistics|smart factory|pneumatic|process control|bioreactor|pharmaceutical|supply chain", 2)],
    "Communications / Wireless": [
        (r"wireless|\b5G\b|communications?|antenna|\bRF\b|radio|(?:massive |\bMIMO\b )(?:MIMO|channel|antenna|system|OFDM|link)|channel model|propagation|modulation|"
         r"signal integrity|\bSDR\b|\bLTE\b|\bWi-?Fi\b|beamforming|radar|SerDes|phase-locked", 2)],
    "Smart Infrastructure / IoT": [
        (r"\bIoT\b|internet of things|smart (?:city|grid|home|building|infrastructure|watering)|infrastructure|"
         r"data cent\w+|ThingSpeak|cloud computing|monitoring system|smart building|urban|coastline|landslide", 2)],
    "Healthcare / Medical": [
        (r"medical|health\w*|patient|clinical|hearing|biomedical|diagnos\w+|neuro\w*|\bEEG\b|\bECG\b|"
         r"pharmaceutical|bioreactor|\bMRI\b|ultrasound|surgery|human motion", 2)],
    "Education / Research": [
        (r"education\w*|\bteaching\b|physics|particle|quark|astronom\w+|"
         r"music|creative|learning platform|scientific|hyperspectral|geoscience", 2)],
    "Finance / Economics": [
        (r"financ\w+|econom\w+|trading|cryptocurrenc\w+|financial market|stock market|stock|portfolio|econometric\w*|"
         r"monetary|Federal Open Market|investment", 2)],
}

AREA_THRESHOLD = 3
# megatrend page -> application area implied by listing (weight 3: sufficient on its own)
TREND_TO_AREA = {
    "Sustainability and Renewable Energy": "Energy / Sustainability",
    "Autonomous Vehicles": "Automotive",
    "Drones": "Aerospace",
    "Robotics": "Robotics / Automation",
    "Industry 4.0": "Manufacturing / Industry 4.0",
    "5G": "Communications / Wireless",
    "Wireless Communication": "Communications / Wireless",
    "Computational Finance": "Finance / Economics",
    "Neuroscience": "Healthcare / Medical",
}
# products imply project types / areas (weight 1 each, capped by threshold arithmetic)
PRODUCT_TO_TYPE = {
    "Deep Learning Toolbox": "AI / Machine Learning", "Statistics and Machine Learning Toolbox": "AI / Machine Learning",
    "Reinforcement Learning Toolbox": "AI / Machine Learning", "Text Analytics Toolbox": "AI / Machine Learning",
    "Control System Toolbox": "Control Design", "Model Predictive Control Toolbox": "Control Design",
    "Robust Control Toolbox": "Control Design", "Simulink Control Design": "Control Design",
    "Motor Control Blockset": "Control Design",
    "Signal Processing Toolbox": "Signal Processing", "DSP System Toolbox": "Signal Processing",
    "Audio Toolbox": "Signal Processing", "Wavelet Toolbox": "Signal Processing", "Radar Toolbox": "Signal Processing",
    "Optimization Toolbox": "Optimization", "Global Optimization Toolbox": "Optimization",
    "Simulink Design Optimization": "Optimization",
    "Embedded Coder": "Embedded / Real-Time", "MATLAB Coder": "Embedded / Real-Time",
    "Simulink Coder": "Embedded / Real-Time", "GPU Coder": "Embedded / Real-Time", "HDL Coder": "Embedded / Real-Time",
    "Simulink Real-Time": "Embedded / Real-Time", "Fixed-Point Designer": "Embedded / Real-Time",
    "Simscape": "Modeling & Simulation", "Simscape Electrical": "Modeling & Simulation",
    "Simscape Multibody": "Modeling & Simulation", "Simscape Fluids": "Modeling & Simulation",
    "Simscape Battery": "Modeling & Simulation", "Simscape Driveline": "Modeling & Simulation",
    "Simulink Test": "Verification / Testing", "Simulink Coverage": "Verification / Testing",
    "Simulink Design Verifier": "Verification / Testing", "Polyspace": "Verification / Testing",
    "Requirements Toolbox": "Verification / Testing", "HDL Verifier": "Verification / Testing",
    "System Composer": "System Design",
    "Predictive Maintenance Toolbox": "Data Analysis", "Econometrics Toolbox": "Data Analysis",
    "Datafeed Toolbox": "Data Analysis", "Database Toolbox": "Data Analysis",
    "ThingSpeak": "Hardware Integration", "Industrial Communication Toolbox": "Hardware Integration",
}
PRODUCT_TO_AREA = {
    "Powertrain Blockset": "Automotive", "Vehicle Dynamics Blockset": "Automotive",
    "Automated Driving Toolbox": "Automotive", "RoadRunner": "Automotive",
    "Aerospace Blockset": "Aerospace", "Aerospace Toolbox": "Aerospace", "UAV Toolbox": "Aerospace",
    "Robotics System Toolbox": "Robotics / Automation", "ROS Toolbox": "Robotics / Automation",
    "Antenna Toolbox": "Communications / Wireless", "Communications Toolbox": "Communications / Wireless",
    "Phased Array System Toolbox": "Communications / Wireless", "RF Toolbox": "Communications / Wireless",
    "Wireless Testbench": "Communications / Wireless", "SerDes Toolbox": "Communications / Wireless",
    "Simscape Battery": "Energy / Sustainability",
    "Medical Imaging Toolbox": "Healthcare / Medical", "SimBiology": "Healthcare / Medical",
    "Financial Toolbox": "Finance / Economics", "Econometrics Toolbox": "Finance / Economics",
    "Datafeed Toolbox": "Finance / Economics",
    "ThingSpeak": "Smart Infrastructure / IoT", "Predictive Maintenance Toolbox": "Manufacturing / Industry 4.0",
    "Industrial Communication Toolbox": "Manufacturing / Industry 4.0",
}
_COMPILED_TYPE = {k: [(re.compile(rx, re.I), w) for rx, w in v] for k, v in PROJECT_TYPE_RULES.items()}
_COMPILED_AREA = {k: [(re.compile(rx, re.I), w) for rx, w in v] for k, v in AREA_RULES.items()}


def _label_scores(compiled, focus: str, body: str) -> dict[str, float]:
    """Score per label: each rule contributes weight*(1 per focus hit up to 2, + min(body hits, 4)*0.25)."""
    out: dict[str, float] = {}
    for label, rules in compiled.items():
        s = 0.0
        for rx, w in rules:
            f = len(rx.findall(focus))
            b = len(rx.findall(body))
            s += w * (min(f, 2) * 1.5 + min(b, 4) * 0.25)
        out[label] = s
    return out


def classify_project_types(title: str, summary: str, expertise: list[str], impact: str, body: str,
                           products: list[str]) -> list[str]:
    focus = " . ".join([title, summary, ", ".join(expertise), impact])
    scores = _label_scores(_COMPILED_TYPE, focus, body)
    for p in products:
        t = PRODUCT_TO_TYPE.get(p)
        if t:
            scores[t] += 1.0
    picked = [l for l in PROJECT_TYPES if scores[l] >= TYPE_THRESHOLD]
    if len(picked) > 4:  # keep the four strongest, canonical order
        top = sorted(picked, key=lambda l: (-scores[l], PROJECT_TYPES.index(l)))[:4]
        picked = [l for l in PROJECT_TYPES if l in top]
    if not picked:
        best = max(PROJECT_TYPES, key=lambda l: (scores[l], -PROJECT_TYPES.index(l)))
        picked = [best if scores[best] > 0 else "System Design"]
    return picked


def classify_application_areas(title: str, summary: str, expertise: list[str], impact: str, body: str,
                               products: list[str], trends: list[str]) -> list[str]:
    focus = " . ".join([title, summary, ", ".join(expertise), impact])
    scores = _label_scores(_COMPILED_AREA, focus, body)
    for t in trends:
        a = TREND_TO_AREA.get(t)
        if a:
            scores[a] += 3.0
    for p in products:
        a = PRODUCT_TO_AREA.get(p)
        if a:
            scores[a] += 1.0
    picked = [l for l in APPLICATION_AREAS if scores[l] >= AREA_THRESHOLD]
    if len(picked) > 3:
        top = sorted(picked, key=lambda l: (-scores[l], APPLICATION_AREAS.index(l)))[:3]
        picked = [l for l in APPLICATION_AREAS if l in top]
    if not picked:
        best = max(APPLICATION_AREAS, key=lambda l: (scores[l], -APPLICATION_AREAS.index(l)))
        picked = [best if scores[best] > 0 else "Education / Research"]
    return picked


# --------------------------------------------------------------------------- difficulty
_UP_WORDS = re.compile(r"\badvanced\b|research[- ]level|state[- ]of[- ]the[- ]art|\bPh\.?D\b|novel|challenging", re.I)
_DOWN_WORDS = re.compile(r"\bbeginner|introductory|entry[- ]level|first project|getting started|no prior experience", re.I)


def classify_difficulty(levels: list[str], difficulty_text: str, body: str, hardware_required: str,
                        sections: dict[str, str] | None = None) -> str:
    """Base level from academic levels, then at most one step of scope adjustment."""
    ls = set(levels)
    if ls == {"Bachelor"}:
        base = 0
    elif "Doctoral" in ls and "Bachelor" not in ls:
        base = 2
    else:
        base = 1  # Master's alone, Bachelor+Master's, all three, or nothing stated
    sections = sections or {}
    adv_work = sections.get("advanced project work", "")
    # "Advanced project work" appears as a sub-heading (###/####) or bold line inside the description.
    m = re.search(r"advanced project work:?\**\s*\n(.*?)(?=\n#{1,4} |\n##|\Z)", body, re.S | re.I)
    adv_items = len(re.findall(r"^\s*(?:[-*]|\d+\.)\s+", m.group(1), re.M)) if m else 0
    if adv_work:
        adv_items = max(adv_items, len(re.findall(r"^\s*(?:[-*]|\d+\.)\s+", adv_work, re.M)))
    up = 0
    down = 0
    if _UP_WORDS.search(difficulty_text):
        up += 1
    if _DOWN_WORDS.search(difficulty_text) or _DOWN_WORDS.search(body[:3000]):
        down += 1
    if adv_items >= 6 and hardware_required == "Required":
        up += 1
    if hardware_required == "Required" and base == 0:
        up += 1
    adjust = 1 if up > down else -1 if down > up else 0
    return DIFFICULTIES[max(0, min(2, base + adjust))]


# --------------------------------------------------------------------------- hardware
# (canonical tag, regex, kind)  kind: "device" always counts; "sensor" only in a hardware-cue sentence
HARDWARE_ROWS: list[tuple[str, str, str]] = [
    ("Raspberry Pi", r"Raspberry\s*Pi", "device"),
    ("Arduino", r"Arduino", "device"),
    ("STM32 / Nucleo", r"STM32|Nucleo|STMicroelectronics\s+(?:board|kit)|Discovery\s+kit", "device"),
    ("NVIDIA Jetson", r"Jetson", "device"),
    ("BeagleBone", r"Beagle\s?Bone", "device"),
    ("Arm Cortex-M", r"Cortex[®-]?-?\s?M\d|ATSAME70", "device"),
    ("Microchip dsPIC / PIC32 / SAM", r"dsPIC|PIC32|MPLAB|Curiosity|Microchip(?:&reg;)?\s+(?:hardware|board|kit)|Timberwolf", "device"),
    ("ESP32", r"ESP32|ESP8266", "device"),
    ("Teensy", r"Teensy", "device"),
    ("FPGA / SoC board", r"FPGA|Zynq|PYNQ|Xilinx|Intel\s+Arria|Cyclone", "device"),
    ("Pixhawk", r"Pixhawk|PX4", "device"),
    ("Parrot Minidrone", r"Parrot|Minidrone|Mambo", "device"),
    ("DJI Tello", r"Tello", "device"),
    ("Crazyflie", r"Crazyflie", "device"),
    ("TurtleBot", r"TurtleBot", "device"),
    ("Universal Robots UR e-Series", r"Universal Robots|\bUR\d+e?\b|\bUR\s*e-?series|URSim", "device"),
    ("Quanser", r"Quanser|QCar|QUBE|QDrone", "device"),
    ("LEGO Mindstorms", r"Mindstorms|LEGO", "device"),
    ("Kinova", r"Kinova", "device"),
    ("ODrive", r"ODrive", "device"),
    ("NI USRP", r"\bUSRP\b|NI\s+(?:SDR|software[- ]defined radio)", "device"),
    ("ADALM-PLUTO SDR", r"ADALM-?PLUTO|\bPluto\s?SDR", "device"),
    ("RTL-SDR", r"RTL-?SDR", "device"),
    ("Software-defined radio", r"software[- ]defined radio|\bSDR\b", "device"),
    ("Analog Devices ADC / evaluation board", r"Analog Devices|\bADI\b", "device"),
    ("Kinect / RealSense", r"Kinect|RealSense", "device"),
    ("Hearing-aid / audio hardware", r"audio interface|MEMS microphone|microphone array", "device"),
    ("Unitree / quadruped robot", r"Unitree|Boston Dynamics", "device"),
    ("Dynamixel servos", r"Dynamixel|servo motors?|\bservos?\b", "device"),
    ("Stepper / DC motor driver", r"motor driver|H-bridge|stepper", "device"),
    ("IMU", r"\bIMUs?\b|inertial measurement unit|accelerometer|gyroscope", "sensor"),
    ("LiDAR", r"\bLiDAR\b", "sensor"),
    ("GPS / GNSS receiver", r"\bGPS\b|\bGNSS\b|\bRTK\b", "sensor"),
    ("Webcam / camera", r"web\s?cam|camera module|onboard camera|USB camera", "sensor"),
    ("Ultrasonic sensor", r"ultrasonic sensor|ultrasound sensor|HC-SR04", "sensor"),
    ("Microphone", r"\bmicrophones?\b", "sensor"),
    ("Temperature / soil sensor", r"temperature sensor|soil moisture|humidity sensor|thermistor", "sensor"),
]
HARDWARE = [(name, re.compile(r"(?<![A-Za-z0-9])(?:" + rx + r")(?![A-Za-z0-9])", re.I if name != "Arm Cortex-M" else 0), kind)
            for name, rx, kind in HARDWARE_ROWS]
_HW_CUE = re.compile(r"real|physical|hardware|onboard|on-board|attach|mount|connect|acquir|stream|deploy|"
                     r"board|kit|prototype|equipped|external", re.I)
_REQUIRED_PHRASES = re.compile(
    r"must be (?:implemented|deployed|run|tested|built|developed) on|hardware (?:is |are )?required|"
    r"requires? (?:the use of |the )?(?:\w+[ -]){0,3}?(?:hardware|board|kit|robot)|"
    r"you will need (?:a |an |the )?(?:\w+[ -]){0,3}?(?:board|kit|robot|hardware)", re.I)
_OPTIONAL_PHRASES = re.compile(
    r"hardware[- ]in[- ]the[- ]loop|\bHIL\b|deploy\w* (?:\w+ ){0,6}?(?:to|on|onto) (?:\w+ ){0,3}?(?:hardware|board|robot|target)|"
    r"real hardware|physical (?:robot|system|hardware|prototype|testbed)|hardware (?:deployment|implementation|platform|testing|validation)|"
    r"low-cost hardware|processor-in-the-loop|\bFPGA\b", re.I)


def detect_hardware_tags(text: str) -> list[str]:
    tags = set()
    sentences = re.split(r"(?<=[.!?])\s+|\n", strip_urls(text))
    for name, rx, kind in HARDWARE:
        if kind == "device":
            if rx.search(text):
                tags.add(name)
        else:
            for s in sentences:
                if rx.search(s) and _HW_CUE.search(s):
                    tags.add(name)
                    break
    return sorted(tags)


def classify_hardware_required(sections: dict[str, str], body: str, tags: list[str]) -> str:
    req = clean_inline(sections.get("required hardware", ""))
    if len(req) >= 10 or _REQUIRED_PHRASES.search(strip_urls(body)):
        return "Required"
    if tags or _OPTIONAL_PHRASES.search(body):
        return "Optional"
    return "None"


# --------------------------------------------------------------------------- partners
DOMAIN_PARTNERS = {
    "microchip.com": "Microchip Technology", "universal-robots.com": "Universal Robots", "st.com": "STMicroelectronics",
    "ni.com": "National Instruments", "iogp.org": "IOGP", "datacor.com": "Datacor", "analog.com": "Analog Devices",
    "arm.com": "Arm", "nvidia.com": "NVIDIA", "intel.com": "Intel", "xilinx.com": "AMD Xilinx", "amd.com": "AMD",
    "quanser.com": "Quanser", "parrot.com": "Parrot", "raspberrypi.com": "Raspberry Pi", "mathworks.com": "",
}
_CORP_SUFFIX = re.compile(r"[,\s]+(?:inc|incorporated|ltd|llc|corp|corporation|gmbh|co|plc)\.?$", re.I)


def normalize_partner(name: str) -> str:
    name = clean_inline(name)
    name = re.sub(r"\([^)]*\)", "", name)
    name = name.replace("&reg;", "").replace("®", "").replace("™", "")
    prev = None
    while prev != name:
        prev = name
        name = _CORP_SUFFIX.sub("", name.strip(" .,;"))
    return name.strip(" .,;")


def partner_from_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    parts = host.split(".")
    for n in (3, 2):
        dom = ".".join(parts[-n:])
        if dom in DOMAIN_PARTNERS:
            return DOMAIN_PARTNERS[dom]
    if len(parts) >= 2 and parts[-2] not in ("co", "com", "org"):
        return parts[-2].upper() if len(parts[-2]) <= 4 else parts[-2].title()
    return ""


def detect_partners(text: str, collab_names: list[str]) -> list[str]:
    """Names from 'in collaboration with' sentences + logo links of an Industry Partner block."""
    names: list[str] = []
    for n in collab_names:
        n = normalize_partner(n)
        if n:
            names.append(n)
    m = re.search(r"Industry[\s_*]+Partners?(?![A-Za-z])", text, re.I)
    if m:
        block = text[m.end(): m.end() + 1500]
        end = re.search(r"\n\s*\n##|<table|\n## ", block)
        if end:
            block = block[: end.start()]
        for a in re.finditer(r"<a\b[^>]*\bhref\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", block, re.S | re.I):
            if "<img" not in a.group(2).lower():
                continue
            n = partner_from_domain(a.group(1))
            if n:
                names.append(n)
    out: list[str] = []
    seen: set[str] = set()
    for n in names:
        key = re.sub(r"[^a-z0-9]", "", n.lower())
        # treat "Analog Devices" and "Analog Devices ADI" style variants as the same company
        if any(key == k or key.startswith(k) or k.startswith(key) for k in seen):
            continue
        seen.add(key)
        out.append(n)
    return out
