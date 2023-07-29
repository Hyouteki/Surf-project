from math import sqrt, pi, sin
from serial import Serial, PARITY_NONE, STOPBITS_ONE, EIGHTBITS
from json import load
from numpy import array, linspace, float64
from matplotlib.pyplot import pause, figure
from scipy.interpolate import splprep, splev
from keyboard import is_pressed
from time import sleep
from csv import writer
from sklearn.cluster import DBSCAN
from pandas import read_csv

"""
units:
    length = mm
    angle  = degree
    delay  = ms
"""

with open("parameters.json") as file:
    parameters = load(file)

# constraints (ultrasonic)
EFFECTUAL_ANGLE: int = parameters["proximity sensor"]["effectual angle"]
MINIMUM_DISTANCE: int = parameters["proximity sensor"]["minimum distance"]
MAXIMUM_DISTANCE: int = parameters["proximity sensor"]["maximum distance"]

# model parameters
LENGTH: int = parameters["workspace"]["length"]
BREADTH: int = parameters["workspace"]["breadth"]
THETA_LENGTH: int = EFFECTUAL_ANGLE
THETA_BREADTH: int = EFFECTUAL_ANGLE
SCALE_LENGTH: int = parameters["scale"]["length"]
SCALE_BREADTH: int = parameters["scale"]["breadth"]
AVERAGE_OF_READINGS: int = parameters["readings"]["average of"]
DELAY_BETWEEN_READINGS: int = parameters["readings"]["delay"]

# constants realated to plotting
X_MIN = -10
X_MAX = LENGTH + 10
Y_MIN = -10
Y_MAX = BREADTH + 10

# constants related to spine interpolation
SPLINE_MAXIMUM_POINTS: int = parameters["spline interpolation"]["maximum points"]
"""number of maximum points in a linear curve"""
SPLINE_MINIMUM_DISTANCE: int = parameters["spline interpolation"]["minimum distance"]
"""minimum distance to interpolate two points"""
SPLINE_MAXIMUM_DISTANCE: int = parameters["spline interpolation"]["maximum distance"]
"""maximum distance to interpolate two points"""

# constants for DBSCAN outlier detection algorithm
EPS: float = parameters["dbscan"]["eps"]
"""radius of neighbourhood"""
MIN_SAMPLES: int = parameters["dbscan"]["minimum samples"]
"""minimum numberr of samples required in neighbourhood to be a inlier"""

# constants related to keyboard instructions
CLEAR = "c"
INTERPOLATE = "i"
OUTLIER_REMOVAL = "o"
SAVE = "s"
IMPORT_FROM_CSV = "b"

# constants related to serial communication
PORT = parameters["serial"]["port"]
BAUD = parameters["serial"]["baud"]

# serial port initialization
ser = Serial(
    port=PORT,
    baudrate=BAUD,
    parity=PARITY_NONE,
    stopbits=STOPBITS_ONE,
    bytesize=EIGHTBITS,
    timeout=0,
)

a, b = 0, 0  # current points
x, y = [], []  # regular points
# points that are to be interpolated and then get added to the points
xToInterpolate, yToInterpolate = [], []
xInterpolated, yInterpolated = [], []  # interpolated points

fig = figure()
axis = fig.add_subplot(111)
axis.set_xlim(X_MIN, X_MAX)
axis.set_ylim(Y_MIN, Y_MAX)
fig.show()

(interpolatedLine,) = axis.plot([], [], "bo")
interpolate = False

# helper methods
degreeToRadian = lambda degree: degree * pi / 180
sq = lambda n: n * n
distanceBetweenPoints = lambda a1, b1, a2, b2: sqrt(sq(a1 - a2) + sq(b1 - b2))

# derived model parameters
COUNTER_TO_LENGTH: int = LENGTH / (2 * sin(degreeToRadian(THETA_LENGTH)))
COUNTER_TO_BREADTH: int = BREADTH / (2 * sin(degreeToRadian(THETA_BREADTH)))


def getSerialInput() -> str:
    """returns serial input without parsing"""
    tmp = ser.readline()
    tmp = tmp.replace(b"\n", b"").replace(b"\r", b"")
    tmp = tmp.decode("utf")
    return tmp


def isInputValid(tmp: str) -> bool:
    """checks whether the input is valid not the coordinate"""
    return sum([1 for z in tmp if z == ","]) == 2 and len(tmp) >= 4


def decodeInput(tmp: str):
    """decodes input and returns a 2d coordinate/point"""
    tmp = tmp[:-1]
    a: int = int(tmp[: tmp.index(",")])
    b: int = int(tmp[tmp.index(",") + 1 :])
    return (a, b)


def isReadingValid(dL: int, dB: int) -> bool:
    """check whether the provided distances are valid or not in accordance with specified parameters"""
    dLMin: int = COUNTER_TO_LENGTH
    dLMax: int = sqrt(sq(COUNTER_TO_LENGTH + BREADTH) + sq(LENGTH / 2))
    dBMin: int = COUNTER_TO_BREADTH
    dBMax: int = sqrt(sq(COUNTER_TO_BREADTH + LENGTH) + sq(BREADTH / 2))
    return dL >= dLMin and dL <= dLMax and dB >= dBMin and dB <= dBMax


def mapToCoordinate(dL: int, dB: int):
    """maps the provided distances to a interger coordinate/point in the first quadrant of the cartesian plane"""
    p: float = dL
    q: float = LENGTH / 2
    r: float = BREADTH + COUNTER_TO_LENGTH
    u: float = dB
    v: float = LENGTH + COUNTER_TO_BREADTH
    w: float = BREADTH / 2
    e: float = sqrt(sq(q - v) + sq(r - w))
    f: float = (sq(p) - sq(u) + sq(e)) / (2 * e)
    g: float = sqrt(sq(p) - sq(f))
    return (
        int((f / e) * (v - q) + (g / e) * (w - r) + q) % LENGTH,
        int((f / e) * (w - r) - (g / e) * (v - q) + r) % BREADTH,
    )


def getCoordinate():
    validCoordinates: int = 0
    a, b = 0, 0
    while validCoordinates < AVERAGE_OF_READINGS:
        serialInput = getSerialInput()
        if not isInputValid(serialInput):
            continue
        # now we have a valid input
        dL, dB = decodeInput(serialInput)
        if not isReadingValid(dL, dB):
            continue
        # now we have a valid reading
        p, q = mapToCoordinate(dL, dB)
        a += p
        b += q
        validCoordinates += 1
    return (a // AVERAGE_OF_READINGS, b // AVERAGE_OF_READINGS)


def update_interpolation() -> None:
    global xInterpolated, yInterpolated
    if interpolate and len(xToInterpolate) > 2:
        # if distance is less than min distance then return
        dis = distanceBetweenPoints(
            xToInterpolate[-1],
            yToInterpolate[-1],
            xToInterpolate[-2],
            yToInterpolate[-2],
        )
        if dis < SPLINE_MINIMUM_DISTANCE and dis > SPLINE_MAXIMUM_DISTANCE:
            return
        # to check if the number of data points is sufficient for cubic spline interpolation (k=3)
        if len(xToInterpolate) >= 3:
            xNpArray = array(xToInterpolate, dtype=float64)
            yNpArray = array(yToInterpolate, dtype=float64)
            tck, _ = splprep([xNpArray, yNpArray], k=2, s=0)
            xInterpolated, yInterpolated = splev(
                linspace(0, 1, SPLINE_MAXIMUM_POINTS), tck
            )
        else:
            xInterpolated = []
            yInterpolated = []
    else:
        xInterpolated = []
        yInterpolated = []
        interpolatedLine.set_data(xInterpolated, yInterpolated)


def drawInterpolation() -> None:
    global xToInterpolate, yToInterpolate
    # appending new points to the coordinates
    xToInterpolate.append(a)
    yToInterpolate.append(b)
    # removing duplicate points
    tmp = set(
        [(xToInterpolate[i], yToInterpolate[i]) for i in range(len(xToInterpolate))]
    )
    xToInterpolate, yToInterpolate = [], []
    for t in tmp:
        xToInterpolate.append(t[0])
        yToInterpolate.append(t[1])
    update_interpolation()
    plotTheDrawing()


def drawPoint() -> None:
    """draws a point on the plot"""
    global x, y
    x.append(a)
    y.append(b)
    plotTheDrawing()


def plotTheDrawing() -> None:
    """function to plot the points"""
    axis.plot(x, y, "bo")
    axis.plot(xToInterpolate, yToInterpolate, "bo")
    axis.plot(xInterpolated, yInterpolated, "r-")
    fig.canvas.draw()


def mergeInterpolatedPoints() -> None:
    """adding interpolated points to general points and clearing interpolated and toInterpolate arrays"""
    global x, y, xInterpolated, yInterpolated, xToInterpolate, yToInterpolate
    x.extend(xInterpolated)
    y.extend(yInterpolated)
    xInterpolated, yInterpolated, xToInterpolate, yToInterpolate = [], [], [], []


def removeOutliers() -> None:
    """Removes outliers present in the plot using DBSCAN algorithm"""
    global x, y, interpolate
    mergeInterpolatedPoints()
    interpolate = False
    points = [[x[i], y[i]] for i in range(len(x))]
    model = DBSCAN(eps=EPS, min_samples=MIN_SAMPLES).fit(points)
    inliers = [
        points[record] for record in range(len(points)) if model.labels_[record] != -1
    ]
    x = [record[0] for record in inliers]
    y = [record[1] for record in inliers]


def savePointsToCSV(fileName: str) -> None:
    """saves coordinates/points to CSV file with fileName"""
    global interpolate
    mergeInterpolatedPoints()
    interpolate = False
    points = [[x[i], y[i]] for i in range(len(x))]
    with open(fileName, "w") as file:
        writer(file).writerows(points)


def importCSVFileToPoints(fileName: str) -> None:
    """imports coordinates/points present in the CSV file"""
    global x, y, interpolate
    mergeInterpolatedPoints()
    interpolate = False
    points = read_csv(fileName, header=None, sep=",").iloc[:, 0:2].values
    x = [record[0] for record in points]
    y = [record[1] for record in points]


if __name__ == "__main__":
    while True:
        if is_pressed(CLEAR):
            print("clear")
            x, y = [], []
            xToInterpolate, yToInterpolate = [], []
            xInterpolated, yInterpolated = [], []
            axis.cla()
            axis.set_xlim(X_MIN, X_MAX)
            axis.set_ylim(Y_MIN, Y_MAX)
        if is_pressed(INTERPOLATE):
            # interpolation is on or off until key pressed again
            interpolate = not interpolate
            print(f"Interpolate = {interpolate}")
            if not interpolate:
                mergeInterpolatedPoints()
        if is_pressed(OUTLIER_REMOVAL):
            removeOutliers()
        if is_pressed(SAVE):
            fileName: str = input("Enter save file name: ") + ".csv"
            savePointsToCSV(fileName)
        if is_pressed(IMPORT_FROM_CSV):
            fileName: str = input("Enter import file name: ") + ".csv"
            importCSVFileToPoints(fileName)
        a, b = getCoordinate()
        print(a, b)
        if interpolate:
            drawInterpolation()
        else:
            drawPoint()
        sleep(DELAY_BETWEEN_READINGS)
        pause(0.001)