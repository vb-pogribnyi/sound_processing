#version 320 es
layout(location = 0) in vec2 apos;
layout(location = 1) in float  height;

uniform float uBarWidth;
uniform float uBarCount;

void main() {
    float index = float(gl_InstanceID);
    float xOffset = (index / uBarCount) * 2.0 - 1.0;
//    float xOffset = (index / 4096.0f) * 2.0 - 1.0;
    vec2 pos = apos;
    pos.x *= uBarWidth;
//    pos.x *= 0.01;
    pos.y *= height * 2.0f;
    pos.x += xOffset;
    pos.y -= 1.0f;
    gl_Position = vec4(pos, 0.0, 1.0);
}