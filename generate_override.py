import yaml
import copy

def generate_override(input_file='docker-compose.yml', output_file='docker-compose.override.yml'):
    # Use 'utf-8-sig' to automatically remove the invisible BOM characters
    with open(input_file, 'r', encoding='utf-8-sig') as f:
        compose_data = yaml.safe_load(f)

    override_data = copy.deepcopy(compose_data)

    for service_name, config in override_data.get('services', {}).items():
        # Remove the ghcr.io image tag entirely so it forces the 'build' block
        if 'image' in config and 'ghcr.io' in config['image']:
            del config['image']
            # Tell docker-compose to build from the local directory instead
            config['build'] = '.'

    # Tell PyYAML to write an empty string instead of 'null'
    yaml.SafeDumper.add_representer(
        type(None),
        lambda dumper, value: dumper.represent_scalar(u'tag:yaml.org,2002:null', u'')
    )

    with open(output_file, 'w', encoding='utf-8') as f:
        yaml.safe_dump(override_data, f, default_flow_style=False, sort_keys=False)

    print(f"Successfully generated {output_file}")

if __name__ == '__main__':
    generate_override()
 