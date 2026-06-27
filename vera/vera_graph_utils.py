import unreal

def get_pin_names(node):
    """
    Returns a dictionary of {'input': [names], 'output': [names]} for a given node.
    Works dynamically across PCG and Blueprint nodes by probing common property names.
    """
    result = {'input': [], 'output': []}
    if not node:
        return result

    # Try Blueprint/Material pins first
    if hasattr(node, 'pins'):
        for pin in node.pins:
            if pin.direction == unreal.EdGraphPinDirection.EGPD_INPUT:
                result['input'].append(str(pin.pin_name))
            else:
                result['output'].append(str(pin.pin_name))
        return result

    # Try PCG pins
    try:
        in_pins = node.get_editor_property('input_pins')
        result['input'] = [str(p.properties.label) for p in in_pins]
    except Exception:
        pass

    try:
        out_pins = node.get_editor_property('output_pins')
        result['output'] = [str(p.properties.label) for p in out_pins]
    except Exception:
        pass

    return result


def find_node_by_type(graph, node_class):
    """
    Searches a graph for the first node matching node_class.
    Handles Blueprints and Material graphs via get_nodes(). 
    For PCG, get_nodes() is not consistently exposed, so it may return None unless specifically wrapped.
    """
    if not graph:
        return None

    # Blueprints / Materials
    if hasattr(graph, 'get_nodes'):
        for node in graph.get_nodes():
            if isinstance(node, node_class):
                return node
                
    # In UE5.3+, PCG Graph nodes can sometimes be accessed via 'get_editor_property'
    try:
        pcg_nodes = graph.get_editor_property('nodes')
        for node in pcg_nodes:
            # The actual node settings are usually the node itself or its settings property
            if isinstance(node, node_class) or (hasattr(node, 'get_settings') and isinstance(node.get_settings(), node_class)):
                return node
    except Exception:
        pass
        
    return None


def connect_nodes(node_a, pin_out_name, node_b, pin_in_name):
    """
    Intelligently connects two nodes regardless of the graph system (Blueprint, Material, PCG).
    Returns True if connection succeeded, False otherwise.
    """
    if not node_a or not node_b:
        return False

    # 1. Blueprint System (EdGraph)
    if hasattr(node_a, 'get_pin') and hasattr(node_b, 'get_pin'):
        pin_a = node_a.get_pin(pin_out_name)
        pin_b = node_b.get_pin(pin_in_name)
        if pin_a and pin_b:
            return pin_a.make_link_to(pin_b)

    # 2. PCG System
    if hasattr(node_a, 'add_edge_to'):
        try:
            node_a.add_edge_to(pin_out_name, node_b, pin_in_name)
            return True
        except Exception:
            return False
            
    # 3. Material System
    # Materials are usually connected via the MaterialEditorLibrary or direct property assignment
    # This acts as a placeholder for material expansion
    return False
