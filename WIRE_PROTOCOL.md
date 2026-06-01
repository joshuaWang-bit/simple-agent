# Wire Protocol

> Auto-generated from bus models. Do not edit manually.

## Commands

### `PingCommand`

**Fields:**

- `type`: `typing.Literal['core.ping']` = `core.ping`
- `client`: `<class 'str'>` = `PydanticUndefined`

**JSON Schema:**
```json
{
  "properties": {
    "type": {
      "const": "core.ping",
      "default": "core.ping",
      "title": "Type",
      "type": "string"
    },
    "client": {
      "title": "Client",
      "type": "string"
    }
  },
  "required": [
    "client"
  ],
  "title": "PingCommand",
  "type": "object"
}
```

**Example:**
```json
{
  "type": "core.ping"
}
```

### `PongResult`

**Fields:**

- `server_version`: `<class 'str'>` = `PydanticUndefined`
- `uptime_ms`: `<class 'int'>` = `PydanticUndefined`
- `received_at`: `<class 'str'>` = `PydanticUndefined`

**JSON Schema:**
```json
{
  "properties": {
    "server_version": {
      "title": "Server Version",
      "type": "string"
    },
    "uptime_ms": {
      "title": "Uptime Ms",
      "type": "integer"
    },
    "received_at": {
      "title": "Received At",
      "type": "string"
    }
  },
  "required": [
    "server_version",
    "uptime_ms",
    "received_at"
  ],
  "title": "PongResult",
  "type": "object"
}
```

**Example:**
```json
{}
```

## Events

### `PlaceholderEvent`

**Fields:**

- `type`: `typing.Literal['placeholder']` = `placeholder`

**JSON Schema:**
```json
{
  "properties": {
    "type": {
      "const": "placeholder",
      "default": "placeholder",
      "title": "Type",
      "type": "string"
    }
  },
  "title": "PlaceholderEvent",
  "type": "object"
}
```

**Example:**
```json
{
  "type": "placeholder"
}
```
