package schema

#ParameterType: "string" | "int" | "bool" | "list_string"

#ArtifactParameter: {
    name:        string
    type:        #ParameterType
    required:    bool | *true
    description: string
    default?:    string | int | bool
}

#ArtifactSpec: {
    name:        =~"^[a-z0-9-]+$"
    version:     int & >=1
    category:    "network" | "process" | "memory" | "filesystem" | "async"
    description: string
    
    parameters: [...#ArtifactParameter]
    
    output_schema: {
        format: "json"
        fields: [string]: string
    }
    
    constraints: {
        max_memory_mb: int & <=64 | *16
        timeout_sec:   int & <=30 | *5
        allow_network: bool | *false
        run_in_ram:    bool | *true
    }
}
