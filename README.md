# IFC OpenShell Export Service

A Flask-based microservice for exporting infrastructure models (chambers, pipes, cable trays, hangers) to IFC format using IfcOpenShell.

## Features

- Export chambers, pipes, cable trays, and hangers to IFC4 format
- Support for multiple unit systems (meters, millimeters, feet, inches)
- Proper coordinate system handling
- Color support for elements
- RESTful API endpoints

## API Endpoints

### Health Check
```
GET /health
```

### Root
```
GET /
```

### Version
```
GET /api/version
```

### Export Chambers
```
POST /api/export-chambers
Content-Type: application/json

{
  "chambers": [...],
  "pipes": [...],
  "cableTrays": [...],
  "hangers": [...],
  "project": {
    "name": "Project Name",
    "origin": {"x": 0, "y": 0, "z": 0},
    "northAngle": 0,
    "elevation": 0,
    "unit": "meters"
  }
}
```

Returns: IFC file as binary download

## Local Development

### Build Docker Image
```bash
docker build -t ifc-openshell-export .
```

### Run Locally
```bash
docker run -p 5001:5001 ifc-openshell-export
```

## Deployment

This service is designed to be deployed on Render or similar container platforms.

### Environment Variables
- `PORT` - Server port (default: 5001)

## License

See main repository for license information.

