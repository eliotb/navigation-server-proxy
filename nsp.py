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
  optional output format (*json* | gpx | kml)

Output:
  Either json or ? gpx track or ? kml

Example usage:
http://localhost:5000/api/v1/yours?origin=-43.5359,172.6395&destination=-43.53479,172.6396&waypoints=1,2,3,4

curl -X POST -H "Content-Type: application/json" -d '{"origin":[-43.538,172.6396],"destination":[-43.5348,172.6430],"waypoints":[[-43,170],[-44,171]]}' http://localhost:5000/api/v1/yours
"""

import urllib2
import flask

app = flask.Flask(__name__)


@app.route('/')
def app_name():
    return 'Route Server Proxy\nby eliot@blennerhassett.gen.nz'


@app.route('/api/v1/<service>', methods=['GET', 'POST'])
def api_v1(service):
    r = flask.request

    query = RouteQuery()
    if r.json is not None:
        query.from_json(r.json)
    else:
        query.from_args(r.args)

    app.logger.info(query)

    routing_service = _routing_services.get(service)
    route = routing_service(query)

    fmt = r.args.get('format', 'json')

    return getattr(route, fmt)()


def loc_from_string(s):
    return [float(x) for x in s.split(',')]

@app.route('/api/osrm/v1', methods=['GET', 'POST'])
def api_osrm():
    r = flask.request
    #app.logger.info('args_query %s' % r.args)
    locs = r.args.getlist('loc', loc_from_string)
    fmt = r.args.get('output', 'gpx')

    q = RouteQuery()
    q.origin = locs[0]
    q.destination = locs[-1]
    q.waypoints = locs[1:-1]
    q.mode = r.args.get('mode', 'car')
    q.validate()

    app.logger.info('api_osrm query=%s' % q)

    route = route_yours(q)
    app.logger.info('api_osrm route=%s' % route)

    res = route.gpx()
    app.logger.info('api_osrm response=%s' % res)
    return route.gpx()


class RouteQuery(dict):
    def __init__(self):
        self.mode = 'car'
        self.waypoints = []
        self.origin = None
        self.destination = None

    def from_args(self, args):
        '''Take url args and return canonical routing request
        '''
        app.logger.info('args_query %s' % args)

        self.origin = [float(x) for x in args['origin'].split(',')]
        self.destination = [float(x) for x in args['destination'].split(',')]
        if 'waypoints' in args:
            wp = [float(x) for x in args['waypoints'].split(',')]
            self.waypoints = list(zip(wp[::2], wp[1::2]))

        self.validate()

    def from_json(self, json):
        '''Take json reqest data and return canonical routing request
        '''
        app.logger.info('json_query %s' % json)

        for attribute in ('origin', 'destination', 'mode', 'waypoints'):
            if attribute in json:
                setattr(self, attribute, json[attribute])

        self.validate()

    def validate(self):
        if self.origin is None:
            raise ValueError('Parameter *origin* is required')

        if self.destination is None:
            raise ValueError('Parameter *destination* is required')

        valid_modes = ['car', 'bicycle', 'pedestrian']
        if not self.mode in valid_modes:
            raise ValueError('Parameter *mode* must be one of %s' % valid_modes)

        if len(self.origin) < 2:
            raise ValueError('Parameter *origin* must have lat and lon')

        if len(self.destination) < 2:
            raise ValueError('Parameter *destination* must have lat and lon')

    def as_dict(self):
        return dict((name, getattr(self, name))
            for name in ('origin', 'destination', 'mode', 'waypoints'))

    def __str__(self):
        return 'RouteQuery(%s)' % str(self.as_dict())


class RouteResult(dict):
    '''
    {'track': [(lat, lon), ...], 'route': [(lat, lon), ...], }
    '''
    def __init__(self, *args, **kwargs):
        self.update(*args, **kwargs)

    def json(self):
        ''' route as json string
        '''
        return flask.jsonify(self)

    def gpx(self):
        route = self.get('route', self.get('track'))
        routepoints = ''
        for c in route:
            routepoints += '<rtept lat="%f" lon="%f" />\n' % c

        # Example routepoint As saved in OsmAnd route gpx
        '''
            <rtept lat="-43.5724628" lon="172.6944566">
              <desc>Keep left and go  250 m</desc>
              <extensions>
                <time>12</time>
                <turn>KL</turn>
                <turn-angle>-5.5384064</turn-angle>
                <offset>93</offset>
              </extensions>
            </rtept>
        '''
        # OsmAnd requires route (?track optional?)
        gpx_route = '<rte>' + routepoints + '</rte>'

        # OsmAnd doesn't need track?, but include it anyway
        track = self.get('track', self.get('route'))
        trackpoints = ''
        for c in track:
            trackpoints += '<trkpt lat="%f" lon="%f" />\n' % c

        gpx_track = '<trk><trkseg>' + trackpoints + '</trkseg></trk>'

        # Example waypoint
        '''
            <wpt lat="-43.5667801" lon="172.6637726">
            <name>Home</name>
            <desc>Home</desc>
            </wpt>
        '''
        wpts = self.get('waypoints', [])
        gpx_waypoints = ''

        s = '\n'.join([
            "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>",
            '<gpx version="1.1" creator="NSP" xmlns="http://www.topografix.com/GPX/1/1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd">',
            gpx_track,
            gpx_route,
            gpx_waypoints,
            '</gpx>'
            ])

        return s


def route_yours(query, format='geojson'):
    '''
        Base URL http://www.yournavigation.org/api/1.0/gosmore.php
        Parameters Available parameters are described below.
        Only the location parameters are required.
        All other parameters are optional,
        they will use the default value when omitted.

        flat = latitude of the starting location.
        flon = longitude of the starting location.
        tlat = latitude of the end location.
        tlon = longitude of the end location.
        v = the type of transport, possible options are: motorcar, bicycle or foot.
        Default is: motorcar.
        fast = 1 selects the fastest route, 0 the shortest route. Default is: 1.
        layer = determines which Gosmore instance is used to calculate the route.
        Provide mapnik for normal routing using car, bicycle or foot.
        Provide cn for using bicycle routing using cycle route networks only.
        Default is: mapnik.
        format = specifies the format (KML or geoJSON) in which the route result is
        being sent back to the client. This can either be kml or geojson.
        Default is: kml.
        geometry = enables/disables adding the route geometry in the output.
        Options are 1 to include route geometry in the output or 0 to exclude it.
        Default is: 1.
        distance = specifies which algorithm is used to calculate the distance.
        Options are v for Vicenty, gc for simplified Great Circle,
        h for Haversine Law, cs for Cosine Law. Default is: v.
        Implemented using the geography class from Simon Holywell.
        instructions = 1/0 to enable/disable adding instructions in the output.
        lang = specifies the language code in which the routing directions are given
    '''
    service = 'http://www.yournavigation.org/api/1.0/gosmore.php'
    instructions = 1
    m = query.mode
    mode = {'car': 'motorcar', 'pedestrian': 'foot'}.get(m, m)

    uri = '%s?format=%s&instructions=%d&flat=%f&flon=%f&tlat=%f&tlon=%f&v=%s' % (
        service, format, instructions,
        query.origin[0],
        query.origin[1],
        query.destination[0],
        query.destination[1],
        mode
        )

    app.logger.info('yours uri = %s' % uri)

    request = urllib2.Request(uri)
    response = urllib2.urlopen(request)
    if format == 'geojson':
        #TODO: munge server response into canonical form here
        '''Typical json response
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

        res = flask.json.load(response)
        c = res['coordinates']
        # coords has lon, lat, [altitude]
        track = []
        for tp in c:
            track.append((tp[1], tp[0])) # track is [(lat, lon), ...]

        return RouteResult({'track': track})
    else:
        #TODO: munge KML into canonical form
        result = ''
        return RouteResult()


def route_ecan(query):
    '''
    See http://resources.arcgis.com/en/help/arcgis-rest-api/index.html#//02r300000036000000
    '''
    service = 'http://arcgisdev.ecan.govt.nz/arcgis/rest/services/OSM/OSMNetwork/NAServer/Route/solve?'
    params = [
        'stops={origin[1]},{origin[0]};{destination[1]},{destination[0]}'.format(**query.as_dict()),
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
    res = RouteResult()
    path = result['routes']['features'][0]['geometry']['paths'][0]
    res['coordinates'] = [(p[1], p[0]) for p in path]
    res['type'] = "LineString"
    app.logger.info('ecan reply = %s' % res)
    return res

_routing_services = {'ecan': route_ecan, 'yours': route_yours}

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
