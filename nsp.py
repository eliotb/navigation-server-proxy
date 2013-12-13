"""
Facade exposing a consistent web API to various routing providers

Input:
  Either (geo)json or URL parameters?
  origin
  destination
  optional waypoints
  optional transport mode (*car* | bike | pedestrian)
  optional route type (*fastest* | shortest | safest | etc)
  optional start time (for routing taking into account predicted congestion)
  optional output format (default json)

Output:
  Either json or ? gpx track or ? kml
"""

import urllib2
import flask

app = flask.Flask(__name__)


@app.route('/')
def app_name():
    return 'Route Server Proxy'


@app.route('/api/v1/<service>', methods=['GET', 'POST'])
def api_v1(service):
    r = flask.request

    if r.json is not None:
        query = json_query(r.json)
    else:
        query = args_query(r.args)

    app.logger.info(query)

    routing_service = routing_services.get(service)
    formatter = formatters.get(r.args.get('format'), formatters['json'])

    return formatter(routing_service(query))



class RouteQuery(object):
    def __init__(self):
        self.mode = 'car'
        self.origin = (0, 0)
        self.destination = (0, 0)
        self.waypoints = []

class RouteResult(object):
    def __init__(self):
        pass


def args_query(args):
    '''Take url args and return canonical routing request
    '''
    app.logger.info('args_query %s' % args)
    query = default_query()
    origin = [float(x) for x in args['origin'].split(',')]
    destination = [float(x) for x in args['destination'].split(',')]
    if 'waypoints' in args:
        wp = [float(x) for x in args['waypoints'].split(',')]
        waypoints = zip(wp[::2], wp[1::2])
        query['waypoints'] = waypoints
    query['origin'] = origin
    query['destination'] = destination

    return validate_query(query)


def json_query(json):
    '''Take json reqest data and return canonical routing request
    '''
    app.logger.info('json_query %s' % json)

    query = default_query()
    for key in query.keys():
        if json.has_key(key):
            query[key] = json[key]

    return validate_query(query)


def default_query():
    return {
        'origin': None,  # latitude, longitude
        'destination': None,  # latitude, longitude
        'waypoints': [],  # lat, long, lat, long, ...
        'mode': 'car',  # pedestrian, bicycle
        'route_type': 'fastest',  # shortest, safest
    }


def validate_query(query):
    if query['origin'] is None:
        raise ValueError('Parameter *origin* is required')

    if query['destination'] is None:
        raise ValueError('Parameter *destination* is required')

    valid_modes = ['car', 'bicycle', 'pedestrian']
    if not query['mode'] in valid_modes:
        raise ValueError('Parameter *mode* must be one of %s' % valid_modes)

    if len(query['origin']) < 2:
        raise ValueError('Parameter *origin* must have lat and lon')

    if len(query['destination']) < 2:
        raise ValueError('Parameter *destination* must have lat and lon')

    return query


def route_json(route):
    '''
    convert route into json
    '''
    return flask.jsonify(route)


def route_gpx(route):
    '''
    convert route into GPX format
    '''
    return str(route)

formatters = {'gpx': route_gpx, 'json': route_json}

def wrap_yours(query):
    '''
    Base URL http://www.yournavigation.org/api/1.0/gosmore.php
    Parameters Available parameters are described below. Only the location parameters are required.
    All other parameters are optional, they will use the default value when omitted.

    flat = latitude of the starting location.
    flon = longitude of the starting location.
    tlat = latitude of the end location.
    tlon = longitude of the end location.
    v = the type of transport, possible options are: motorcar, bicycle or foot. Default is: motorcar.
    fast = 1 selects the fastest route, 0 the shortest route. Default is: 1.
    layer = determines which Gosmore instance is used to calculate the route. Provide mapnik for normal routing using car, bicycle or foot. Provide cn for using bicycle routing using cycle route networks only. Default is: mapnik.
    format = specifies the format (KML or geoJSON) in which the route result is being sent back to the client. This can either be kml or geojson. Default is: kml.
    geometry = enables/disables adding the route geometry in the output. Options are 1 to include the route geometry in the output or 0 to exclude it. Default is: 1.
    distance = specifies which algorithm is used to calculate the distance. Options are v for Vicenty, gc for simplified Great Circle, h for Haversine Law, cs for Cosine Law. Default is: v. Implemented using the geography class from Simon Holywell.
    instructions = enbles/disables adding driving instructions in the output. Options are 1 to include driving directions, 0 to disable driving directions. Default is 0.
    lang = specifies the language code in which the routing directions are given
    '''
    service = 'http://www.yournavigation.org/api/1.0/gosmore.php'
    instructions = 1
    m = query['mode']
    mode = {'car': 'motorcar', 'pedestrian': 'foot'}.get(m, m)

    uri = '%s?format=geojson&instructions=%d&flat=%f&flon=%f&tlat=%f&tlon=%f&v=%s' % (
        service, instructions,
        query['origin'][0],
        query['origin'][1],
        query['destination'][0],
        query['destination'][1],
        mode
        )

    app.logger.info('yours uri = %s' % uri)

    request = urllib2.Request(uri)
    response = urllib2.urlopen(request)
    result = flask.json.load(response)
    #TODO: munge server response into canonical form here
    '''Typical response
    {
  "crs": {
    "type": "name",
    "properties": {
      "name": "urn:ogc:def:crs:OGC:1.3:CRS84"
    }
  },
  "type": "LineString",
  "properties": {
    "distance": "0.145438",
    "description": "Continue on Manchester Street. Follow the road for 0.1 mi.<br>Turn left into Struthers Lane. Follow the road for 0.0 mi.<br>Continue on fini.<br>",
    "traveltime": "40"
  },
  "coordinates": [
    [
      172.6397,
      -43.5359
    ],
    [
      172.6397,
      -43.535326
    ],
    [
      172.63969,
      -43.534802
    ],
    [
      172.6396,
      -43.534802
    ]
  ]
}'''
    return result


def wrap_ecan(query):
    '''
    See http://resources.arcgis.com/en/help/arcgis-rest-api/index.html#//02r300000036000000
    '''
    service = 'http://arcgisdev.ecan.govt.nz/arcgis/rest/services/OSM/OSMNetwork/NAServer/Route/solve?'
    params = [
        'stops={origin[1]},{origin[0]};{destination[1]},{destination[0]}&'.format(**query),
        'f=json',
        'barriers=',
        'polylineBarriers=',
        'polygonBarriers=',
        'outSR=',
        'ignoreInvalidLocations=trueaccumulateAttributeNames=',
        'impedanceAttributeName=Length',
        'restrictionAttributeNames=Oneway',
        'attributeParameterValues=',
        'restrictUTurns=esriNFSBAllowBacktrack',
        'useHierarchy=false',
        'returnDirections=true',
        'returnRoutes=true',
        'returnStops=false',
        'returnBarriers=false',
        'returnPolylineBarriers=false',
        'returnPolygonBarriers=false',
        'directionsLanguage=en',
        'directionsStyleName=',
        'outputLines=esriNAOutputLineTrueShapeWithMeasure',
        'findBestSequence=false',
        'preserveFirstStop=false',
        'preserveLastStop=false',
        'useTimeWindows=false',
        'startTime=0',
        'outputGeometryPrecision=',
        'outputGeometryPrecisionUnits=esriDecimalDegrees',
        'directionsOutputType=esriDOTComplete',
        'directionsTimeAttributeName=',
        'directionsLengthUnits=esriNAUKilometers',
        'returnZ=false'
    ]

    uri = service + '&'.join(params)
    app.logger.info('ecan uri = %s' % uri)

    request = urllib2.Request(uri)
    response = urllib2.urlopen(request)
    result = flask.json.load(response)
    #TODO: now convert this result into canonical result
    ''' Typical response
    {
  "routes": {
    "fieldAliases": {
      "FirstStopID": "FirstStopID",
      "Name": "Name",
      "ObjectID": "ObjectID",
      "Shape_Length": "Shape_Length",
      "StopCount": "StopCount",
      "Total_Length": "Total_Length",
      "LastStopID": "LastStopID"
    },
    "hasM": true,
    "geometryType": "esriGeometryPolyline",
    "features": [
      {
        "geometry": {
          "hasM": true,
          "paths": [
            [
              [
                  What are these big numbers? Expected lon,lat?
                19218163.123999998,
                -5393900.276900001,
                0
              ],
              [
                19218163.0272,
                -5393812.175500002,
                88.10149189157487
              ],
              [
                19218162.949199997,
                -5393731.697799999,
                168.579187944293
              ],
              [
                19218162.934199996,
                -5393729.772700001,
                170.50434538195134
              ]
            ]
          ]
        },
        "attributes": {
          "FirstStopID": 1,
          "Name": "Location 1 - Location 2",
          "ObjectID": 1,
          "Shape_Length": 170.50434941594693,
          "StopCount": 2,
          "Total_Length": 170.5043453819461,
          "LastStopID": 2
        }
      }
    ],
    "spatialReference": {
      "wkid": 102100,
      "latestWkid": 3857
    }
  },
  "directions": [
    {
      "hasM": true,
      "routeName": "Location 1 - Location 2",
      "features": [
        {
          "attributes": {
            "text": "Start at Location 1",
            "length": 0,
            "ETA": -2209161600000,
            "maneuverType": "esriDMTDepart",
            "time": 0
          },
          "compressedGeometry": "+0+1+2+1+iafnj-54jfb+0+0|+9+0+0"
        },
        {
          "attributes": {
            "text": "Go north on Manchester Street secondary toward Tuam Street residential",
            "length": 0.17050434538194612,
            "ETA": -2209161600000,
            "maneuverType": "esriDMTStraight",
            "time": 0
          },
          "strings": [
            {
              "stringType": "esriDSTStreetName",
              "string": "Manchester Street secondary"
            },
            {
              "stringType": "esriDSTCrossStreet",
              "string": "Tuam Street residential"
            }
          ],
          "compressedGeometry": "+0+1+2+1+iafnj-54jfb+0+5a|+9+0+1fv"
        },
        {
          "attributes": {
            "text": "Finish at Location 2, on the left",
            "length": 0,
            "ETA": -2209161600000,
            "maneuverType": "esriDMTStop",
            "time": 0
          },
          "compressedGeometry": "+0+1+2+1+iafnj-54ja1+0+0|+9+1fv+0"
        }
      ],
      "summary": {
        "totalTime": 0,
        "totalLength": 0.17050434538194612,
        "totalDriveTime": 0,
        "envelope": {
          "xmin": 19218141.230800003,
          "ymin": -5393900.300999999,
          "ymax": -5393729.772742729,
          "xmax": 19218163.124026127,
          "spatialReference": {
            "wkid": 102100,
            "latestWkid": 3857
          }
        }
      },
      "routeId": 1
    }
  ],
  "messages": [
    {
      "type": 50,
      "description": "The start time was ignored because the impedance attribute is not time-based."
    }
  ]
}'''

    app.logger.info('ecan result = %s' % result)
    res = {}
    path = result['routes']['features'][0]['geometry']['paths'][0]
    res['coordinates'] = [(p[1], p[0]) for p in path]
    res['type'] = "LineString"
    app.logger.info('ecan reply = %s' % res)
    return res

routing_services = {'ecan': wrap_ecan, 'yours': wrap_yours}

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
