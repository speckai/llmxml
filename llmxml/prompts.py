def ADHERE_INSTRUCTIONS_PROMPT(schema: str) -> str:
    return (
        """
You are to provide your output in the following xml-like format EXACTLY as described in the schema provided.
Each field in the schema has a description and a type enclosed in square brackets, denoting that they are metadata.
Format instructions:
<field_name>
[object_type]
[required/optional]
[description]
</field_name>

Basic example:
<EXAMPLE>
<EXAMPLE_SCHEMA>
<thinking>
[type: str]
[optional]
[Chain of thought]
</thinking>
<actions>
# Option 1: CommandAction
<command_action>
<action_type>
[type: Literal["command"]]
[required]
[The type of action to perform]
</action_type>
<command>
[type: str]
[required]
[The command to run]
</command>
</command_action>

OR

# Option 2: CreateAction
<create_action>
<action_type>
[type: Literal["create"]]
[required]
[The type of action to perform]
</action_type>
<new_file_path>
[type: str]
[required]
[The path to the new file to create]
</new_file_path>
<file_contents>
[type: str]
[required]
[The contents of the new file to create]
</file_contents>
</create_action>

OR

# Option 3: EditAction
<edit_action>
<action_type>
[type: Literal["edit"]]
[required]
[The type of action to perform]
</action_type>
<original_file_path>
[type: str]
[required]
[The path to the original file to edit]
</original_file_path>
<new_file_contents>
[type: str]
[required]
[The contents of the edited file]
</new_file_contents>
</edit_action>
</actions>
</EXAMPLE_SCHEMA>

<EXAMPLE_OUTPUT>
<thinking>
First, I need to create a new configuration file. Then, I'll modify an existing source file to use the new configuration.
</thinking>
<actions>
<create_action>
<action_type>create</action_type>
<new_file_path>config/settings.json</new_file_path>
<file_contents>interface Config {
  apiKey: string;
  baseUrl: string;
  timeout: number;
}
const config: Config = {
  apiKey: "your-api-key-here",
  baseUrl: "https://api.example.com",
  timeout: 30
};</file_contents>
</create_action>
<edit_action>
<action_type>edit</action_type>
<original_file_path>src/main.py</original_file_path>
<new_file_contents>import json
def load_config():
    with open('config/settings.json', 'r') as f:
        return json.load(f)
def main():
    config = load_config()
    print(f"Connecting to {config['base_url']}...")
if __name__ == '__main__':
    main()
</new_file_contents>
</edit_action>
</actions>
</EXAMPLE_OUTPUT>
</EXAMPLE>
""".strip()
        + "\n\n"
        + f"""
Requested Response Schema:
{schema}
Make sure to return an instance of the output, NOT the schema itself. Do NOT include any schema metadata (like [type: ...]) in your output.
""".strip()
    )


def ADHERE_INSTRUCTIONS_PROMPT_GENERAL(schema: str) -> str:
    return (
        """
You are to provide your output in the following xml-like format EXACTLY as described in the schema provided.
Each field in the schema has a description, type, and requirement status enclosed in square brackets, denoting that they are metadata.
Format instructions:
<field_name>
[type: object_type]
[required/optional]
[description]
</field_name>

Basic example:
<EXAMPLE>
<EXAMPLE_SCHEMA>
<reasoning>
[type: str]
[optional]
[Detailed thought process explaining the approach]
</reasoning>
<actions>
# Option 1: DirectAction
<direct_action>
<action_type>
[type: Literal["direct"]]
[required]
[Immediate action to be performed]
</action_type>
<instruction>
[type: str]
[required]
[The specific instruction to execute]
</instruction>
<priority>
[type: str]
[optional]
[Priority level of the action]
</priority>
</direct_action>

OR # Option 2: GenerateAction
<generate_action>
<action_type>
[type: Literal["generate"]]
[required]
[Creation of new content/resource]
</action_type>
<resource_identifier>
[type: str]
[required]
[Unique identifier for the new resource]
</resource_identifier>
<resource_content>
[type: str]
[required]
[The content/data to be generated]
</resource_content>
<metadata>
[type: str]
[optional]
[Additional information about the resource]
</metadata>
</generate_action>

OR # Option 3: ModifyAction
<modify_action>
<action_type>
[type: Literal["modify"]]
[required]
[Modification of existing content/resource]
</action_type>
<target_identifier>
[type: str]
[required]
[Identifier of the resource to modify]
</target_identifier>
<updated_content>
[type: str]
[required]
[The modified content/data]
</updated_content>
<backup_needed>
[type: bool]
[optional]
[Whether to create backup before modification]
</backup_needed>
</modify_action>
</actions>
</EXAMPLE_SCHEMA>

<EXAMPLE_OUTPUT>
<reasoning>
To accomplish the task, we'll first generate a new configuration resource with required parameters, then modify an existing resource while ensuring we create a backup.
</reasoning>
<actions>
<generate_action>
<action_type>generate</action_type>
<resource_identifier>resources/config.json</resource_identifier>
<resource_content>{
  "type": "configuration",
  "parameters": {
    "primary": "value1",
    "secondary": "value2",
    "timeout": 30
  }
}</resource_content>
<metadata>Version: 1.0, Environment: Production</metadata>
</generate_action>

<modify_action>
<action_type>modify</action_type>
<target_identifier>resources/main.json</target_identifier>
<updated_content>{
  "type": "resource",
  "dependencies": ["configuration"],
  "properties": {
    "uses_config": true,
    "version": "1.0"
  }
}</updated_content>
<backup_needed>true</backup_needed>
</modify_action>
</actions>
</EXAMPLE_OUTPUT>
</EXAMPLE>
""".strip()
        + "\n\n"
        + f"""
Requested Response Schema:
{schema}

Make sure to return an instance of the output, NOT the schema itself. Do NOT include any schema metadata (like [type: ...]) in your output.
""".strip()
    )
