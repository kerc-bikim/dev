/**
 * Minimal WebGL batch renderer for colored quads (the PPSD histogram cells).
 * Geometry is supplied in CSS-pixel coordinates of the plot area; the shader
 * maps those to clip space using the plot-area resolution.
 */

const VERT_SRC = `
attribute vec2 a_pos;
attribute vec3 a_color;
uniform vec2 u_resolution;
varying vec3 v_color;
void main() {
  vec2 clip = (a_pos / u_resolution) * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
  v_color = a_color;
}
`;

const FRAG_SRC = `
precision mediump float;
varying vec3 v_color;
void main() {
  gl_FragColor = vec4(v_color, 1.0);
}
`;

function compile(gl: WebGLRenderingContext, type: number, src: string) {
  const sh = gl.createShader(type)!;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    const log = gl.getShaderInfoLog(sh);
    gl.deleteShader(sh);
    throw new Error(`WebGL shader compile failed: ${log}`);
  }
  return sh;
}

export class WebGLQuadLayer {
  private gl: WebGLRenderingContext;
  private program: WebGLProgram;
  private posBuf: WebGLBuffer;
  private colorBuf: WebGLBuffer;
  private aPos: number;
  private aColor: number;
  private uResolution: WebGLUniformLocation | null;

  constructor(private canvas: HTMLCanvasElement) {
    const gl =
      canvas.getContext("webgl", { antialias: true, preserveDrawingBuffer: true }) ||
      canvas.getContext("experimental-webgl");
    if (!gl) throw new Error("WebGL is not supported in this browser.");
    this.gl = gl as WebGLRenderingContext;

    const vs = compile(this.gl, this.gl.VERTEX_SHADER, VERT_SRC);
    const fs = compile(this.gl, this.gl.FRAGMENT_SHADER, FRAG_SRC);
    const program = this.gl.createProgram()!;
    this.gl.attachShader(program, vs);
    this.gl.attachShader(program, fs);
    this.gl.linkProgram(program);
    if (!this.gl.getProgramParameter(program, this.gl.LINK_STATUS)) {
      throw new Error(`WebGL link failed: ${this.gl.getProgramInfoLog(program)}`);
    }
    this.program = program;
    this.aPos = this.gl.getAttribLocation(program, "a_pos");
    this.aColor = this.gl.getAttribLocation(program, "a_color");
    this.uResolution = this.gl.getUniformLocation(program, "u_resolution");
    this.posBuf = this.gl.createBuffer()!;
    this.colorBuf = this.gl.createBuffer()!;
  }

  /**
   * @param positions Float32Array of x,y pairs (2 per vertex), CSS px of plot area
   * @param colors    Float32Array of r,g,b triples (0..1) per vertex
   * @param cssWidth  plot-area width in CSS px
   * @param cssHeight plot-area height in CSS px
   */
  draw(
    positions: Float32Array,
    colors: Float32Array,
    cssWidth: number,
    cssHeight: number
  ) {
    const gl = this.gl;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.max(1, Math.round(cssWidth * dpr));
    this.canvas.height = Math.max(1, Math.round(cssHeight * dpr));
    this.canvas.style.width = `${cssWidth}px`;
    this.canvas.style.height = `${cssHeight}px`;

    gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.program);
    gl.uniform2f(this.uResolution, cssWidth, cssHeight);

    gl.bindBuffer(gl.ARRAY_BUFFER, this.posBuf);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(this.aPos);
    gl.vertexAttribPointer(this.aPos, 2, gl.FLOAT, false, 0, 0);

    gl.bindBuffer(gl.ARRAY_BUFFER, this.colorBuf);
    gl.bufferData(gl.ARRAY_BUFFER, colors, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(this.aColor);
    gl.vertexAttribPointer(this.aColor, 3, gl.FLOAT, false, 0, 0);

    gl.drawArrays(gl.TRIANGLES, 0, positions.length / 2);
  }

  dispose() {
    const gl = this.gl;
    gl.deleteBuffer(this.posBuf);
    gl.deleteBuffer(this.colorBuf);
    gl.deleteProgram(this.program);
  }
}
