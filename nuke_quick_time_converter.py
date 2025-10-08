import sys
import json
import os

try:
    import nuke
except ImportError:
    print("Nuke not available")
    sys.exit(1)

def convert_with_nuke(input_path, output_path, scale, codec, colorspace="sRGB"):
    try:
        # Создаем Read node
        read_node = nuke.createNode("Read")
        read_node["file"].setValue(input_path)
        
        # Добавляем Reformat node если нужно масштабирование
        if scale != "none":
            reformat = nuke.createNode("Reformat")
            if "/" in scale:
                reformat["type"].setValue("scale")
                reformat["scale"].setValue(float(eval(scale)))
            reformat.setInput(0, read_node)
            input_node = reformat
        else:
            input_node = read_node
        
        # Создаем Write node
        write_node = nuke.createNode("Write")
        write_node["file"].setValue(output_path)
        write_node["file_type"].setValue("mov")
        
        # Настраиваем кодек
        if codec == "prores":
            write_node["mov64_codec"].setValue("apco")
        elif codec == "mjpeg":
            write_node["mov64_codec"].setValue("jpeg")
        
        write_node.setInput(0, input_node)
        
        # Выполняем рендер
        nuke.execute(write_node, 1, 1)
        
        # Удаляем ноды
        nuke.delete(write_node)
        if scale != "none":
            nuke.delete(reformat)
        nuke.delete(read_node)
        
        return True
    except Exception as e:
        print(f"Conversion error: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Usage: nuke -t script.py <json_path>")
        sys.exit(1)
    
    json_path = sys.argv[1]
    
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        for input_path, output_path in data["media"]:
            success = convert_with_nuke(
                input_path, 
                output_path, 
                data["scale"], 
                data["codec"],
                data.get("output_colorspace", "sRGB")
            )
            if success:
                print(f"Success: {input_path} -> {output_path}")
            else:
                print(f"Failed: {input_path}")
                
    except Exception as e:
        print(f"Error processing JSON: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
