const MAX_POINT_COUNT = 300000;

function normalizedColors(attribute, vertexCount) {
  if (!attribute) return null;
  const colors = new Float32Array(vertexCount * 4);
  const divisor = attribute.normalized ? 255 : 1;
  for (let index = 0; index < vertexCount; index += 1) {
    const source = index * attribute.size;
    const target = index * 4;
    colors[target] = attribute.value[source] / divisor;
    colors[target + 1] = attribute.value[source + 1] / divisor;
    colors[target + 2] = attribute.value[source + 2] / divisor;
    colors[target + 3] = attribute.size > 3 ? attribute.value[source + 3] / divisor : 1;
  }
  return colors;
}

async function addStandardPly(scene, url, modules, signal) {
  const { parsePly } = await import("./plyParser.js");
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`Could not load PLY (${response.status})`);
  const buffer = await response.arrayBuffer();
  const parsed = parsePly(buffer, { maxPointCount: MAX_POINT_COUNT });
  const isPoints = parsed.topology === "point-list";
  const originalCount = parsed.originalVertexCount;
  const attributes = parsed.attributes;
  const vertexCount = attributes.POSITION.value.length / 3;
  const mesh = new modules.Mesh("ply", scene);
  const geometry = new modules.VertexData();
  geometry.positions = attributes.POSITION.value;
  geometry.normals = attributes.NORMAL?.value ?? null;
  geometry.uvs = attributes.TEXCOORD_0?.value ?? null;
  geometry.colors = normalizedColors(attributes.COLOR_0, vertexCount);
  geometry.indices = isPoints ? null : parsed.indices?.value;
  if (!isPoints && !geometry.normals?.length && geometry.indices?.length) {
    geometry.normals = [];
    modules.VertexData.ComputeNormals(
      geometry.positions,
      geometry.indices,
      geometry.normals,
    );
  }
  geometry.applyToMesh(mesh);
  const material = new modules.StandardMaterial("ply-material", scene);
  material.backFaceCulling = false;
  material.pointsCloud = isPoints;
  material.pointSize = 2;
  material.diffuseColor = new modules.Color3(0.58, 0.64, 0.72);
  material.emissiveColor = isPoints
    ? new modules.Color3(0.16, 0.16, 0.16)
    : modules.Color3.Black();
  mesh.material = material;
  return { meshes: [mesh], originalCount, renderedCount: vertexCount };
}

function createEnvironment(scene, modules, dark) {
  const light = new modules.HemisphericLight(
    "ambient",
    new modules.Vector3(0.2, 1, 0.1),
    scene,
  );
  light.intensity = 1.15;
  const grid = modules.MeshBuilder.CreateGround(
    "grid",
    { width: 20, height: 20, subdivisions: 20 },
    scene,
  );
  const gridMaterial = new modules.StandardMaterial("grid-material", scene);
  gridMaterial.wireframe = true;
  gridMaterial.alpha = 0.22;
  gridMaterial.diffuseColor = dark
    ? new modules.Color3(0.48, 0.51, 0.58)
    : new modules.Color3(0.28, 0.31, 0.38);
  gridMaterial.emissiveColor = gridMaterial.diffuseColor;
  grid.material = gridMaterial;
  grid.isPickable = false;
  const axes = new modules.AxesViewer(scene, 1.6);
  return { grid, axes };
}

function frameCamera(camera, meshes) {
  const visible = meshes.filter((mesh) => mesh?.getBoundingInfo && mesh.isEnabled());
  if (!visible.length) return;
  camera.zoomOn(visible, true);
  camera.lowerRadiusLimit = Math.max(camera.radius * 0.01, 0.001);
  camera.upperRadiusLimit = Math.max(camera.radius * 100, 100);
}

export async function createObject3DViewer(canvas, item, url, updateStatus, signal) {
  const [
    { Engine },
    { Scene },
    { ArcRotateCamera },
    { Vector3 },
    { Color3, Color4 },
    { HemisphericLight },
    { Mesh },
    { MeshBuilder },
    { VertexData },
    { StandardMaterial },
    { AxesViewer },
    { ImportMeshAsync },
    loader,
  ] = await Promise.all([
    import("@babylonjs/core/Engines/engine.js"),
    import("@babylonjs/core/scene.js"),
    import("@babylonjs/core/Cameras/arcRotateCamera.js"),
    import("@babylonjs/core/Maths/math.vector.js"),
    import("@babylonjs/core/Maths/math.color.js"),
    import("@babylonjs/core/Lights/hemisphericLight.js"),
    import("@babylonjs/core/Meshes/mesh.js"),
    import("@babylonjs/core/Meshes/meshBuilder.js"),
    import("@babylonjs/core/Meshes/mesh.vertexData.js"),
    import("@babylonjs/core/Materials/standardMaterial.js"),
    import("@babylonjs/core/Debug/axesViewer.js"),
    import("@babylonjs/core/Loading/sceneLoader.js"),
    import("@babylonjs/loaders/dynamic"),
  ]);
  if (signal?.aborted) throw new DOMException("Viewer load cancelled", "AbortError");
  const core = {
    Engine,
    Scene,
    ArcRotateCamera,
    Vector3,
    Color3,
    Color4,
    HemisphericLight,
    Mesh,
    MeshBuilder,
    VertexData,
    StandardMaterial,
    AxesViewer,
    ImportMeshAsync,
  };
  loader.registerBuiltInLoaders();
  const engine = new core.Engine(canvas, true, {
    preserveDrawingBuffer: false,
    stencil: true,
  });
  const scene = new core.Scene(engine);
  const dark = document.documentElement.dataset.theme === "dark";
  scene.clearColor = dark
    ? new core.Color4(0.045, 0.052, 0.065, 1)
    : new core.Color4(0.93, 0.945, 0.965, 1);
  const camera = new core.ArcRotateCamera(
    "camera",
    Math.PI / 4,
    Math.PI / 3,
    6,
    core.Vector3.Zero(),
    scene,
  );
  camera.attachControl(canvas, true);
  camera.wheelDeltaPercentage = 0.01;
  camera.panningSensibility = 120;
  const environment = createEnvironment(scene, core, dark);
  let loadedMeshes = [];
  let resizeObserver;
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    signal?.removeEventListener("abort", dispose);
    resizeObserver?.disconnect();
    camera.detachControl();
    engine.stopRenderLoop();
    scene.dispose();
    engine.dispose();
  };
  signal?.addEventListener("abort", dispose, { once: true });

  try {
    if (signal?.aborted) throw new DOMException("Viewer load cancelled", "AbortError");
    let counts = {};
    if (item.format === "ply" && item.kind !== "gaussian_splat") {
      const result = await addStandardPly(scene, url, core, signal);
      loadedMeshes = result.meshes;
      counts = {
        originalPointCount: result.originalCount,
        renderedPointCount: result.renderedCount,
      };
    } else {
      const result = await core.ImportMeshAsync(url, scene);
      if (signal?.aborted) throw new DOMException("Viewer load cancelled", "AbortError");
      loadedMeshes = result.meshes;
      for (const animation of result.animationGroups) animation.start(true);
    }
    if (signal?.aborted) throw new DOMException("Viewer load cancelled", "AbortError");
    frameCamera(camera, loadedMeshes);
    updateStatus({ state: "ready", ...counts });
  } catch (error) {
    dispose();
    if (error?.name === "AbortError") throw error;
    const message = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Unable to render ${item.format?.toUpperCase() || "3D object"}: ${message}`,
      { cause: error },
    );
  }

  engine.runRenderLoop(() => scene.render());
  resizeObserver = new ResizeObserver(() => engine.resize());
  resizeObserver.observe(canvas);

  return {
    resetCamera() {
      frameCamera(camera, loadedMeshes);
    },
    setGridVisible(visible) {
      environment.grid.setEnabled(visible);
    },
    setAxesVisible(visible) {
      environment.axes.xAxis.setEnabled(visible);
      environment.axes.yAxis.setEnabled(visible);
      environment.axes.zAxis.setEnabled(visible);
    },
    dispose,
  };
}

export { MAX_POINT_COUNT };
