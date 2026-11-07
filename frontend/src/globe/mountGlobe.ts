import {
  ArcGisMapServerImageryProvider,
  ArcType,
  Cartesian2,
  Cartesian3,
  Color,
  ConstantPositionProperty,
  ImageryLayer,
  JulianDate,
  LabelStyle,
  PolygonHierarchy,
  VerticalOrigin,
  Viewer,
} from "cesium";
import type { TrackPoint } from "../orbitTrack";
import type { SaaBox } from "../types";

export type GlobeHandle = {
  setTime: (at: Date, fix: TrackPoint | null) => void;
  destroy: () => void;
};

export type MountGlobeInput = {
  container: HTMLElement;
  satelliteId: string;
  saa: SaaBox;
  orbit: TrackPoint[];
  anomaly: TrackPoint[];
  anomalyStart: TrackPoint | null;
  initialTime: Date;
  initialFix: TrackPoint | null;
};

const IMAGERY_URL = "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer";

export async function mountGlobe(input: MountGlobeInput): Promise<GlobeHandle> {
  let baseLayer: ImageryLayer | false = false;
  try {
    const imagery = await ArcGisMapServerImageryProvider.fromUrl(IMAGERY_URL);
    baseLayer = new ImageryLayer(imagery);
    baseLayer.nightAlpha = 0.45;
  } catch {
    baseLayer = false;
  }

  const viewer = new Viewer(input.container, {
    animation: false,
    timeline: false,
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    baseLayer,
    requestRenderMode: true,
  });
  viewer.canvas.tabIndex = -1;
  viewer.scene.globe.enableLighting = true;
  viewer.scene.globe.dynamicAtmosphereLighting = true;
  viewer.scene.globe.dynamicAtmosphereLightingFromSun = true;
  viewer.clock.shouldAnimate = false;
  viewer.clock.currentTime = JulianDate.fromDate(input.initialTime);

  const saa = input.saa;
  const ring = [
    saa.lonMin, saa.latMin,
    saa.lonMax, saa.latMin,
    saa.lonMax, saa.latMax,
    saa.lonMin, saa.latMax,
  ];
  viewer.entities.add({
    name: "South Atlantic Anomaly",
    polygon: {
      hierarchy: new PolygonHierarchy(Cartesian3.fromDegreesArray(ring)),
      material: Color.fromCssColorString("#f59e0b").withAlpha(0.33),
      height: 0,
    },
  });
  viewer.entities.add({
    polyline: {
      positions: Cartesian3.fromDegreesArray([...ring, saa.lonMin, saa.latMin]),
      width: 2,
      material: Color.fromCssColorString("#fbbf24"),
      arcType: ArcType.RHUMB,
      clampToGround: true,
    },
  });
  addTrack(viewer, input.orbit, "#67e8f9", 2);
  addTrack(viewer, input.anomaly, "#f8fafc", 4);

  const position = new ConstantPositionProperty(toCartesian(input.initialFix ?? input.anomalyStart));
  viewer.entities.add({
    name: input.satelliteId,
    position,
    point: {
      pixelSize: 12,
      color: Color.fromCssColorString("#22d3ee"),
      outlineColor: Color.WHITE,
      outlineWidth: 2,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
    label: {
      text: input.satelliteId,
      font: "14px IBM Plex Sans, sans-serif",
      fillColor: Color.WHITE,
      outlineColor: Color.BLACK,
      outlineWidth: 2,
      style: LabelStyle.FILL_AND_OUTLINE,
      pixelOffset: new Cartesian2(14, 0),
      verticalOrigin: VerticalOrigin.CENTER,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
    },
  });
  if (input.anomalyStart) {
    viewer.entities.add({
      name: "Anomaly start",
      position: toCartesian(input.anomalyStart),
      point: {
        pixelSize: 8,
        color: Color.WHITE,
        outlineColor: Color.fromCssColorString("#0f172a"),
        outlineWidth: 1,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }

  const observer = new ResizeObserver(() => {
    viewer.resize();
    viewer.scene.requestRender();
  });
  observer.observe(input.container);
  void viewer.zoomTo(viewer.entities);
  viewer.scene.requestRender();

  return {
    setTime(at: Date, fix: TrackPoint | null) {
      viewer.clock.currentTime = JulianDate.fromDate(at);
      if (fix) {
        position.setValue(toCartesian(fix));
      }
      viewer.scene.requestRender();
    },
    destroy() {
      observer.disconnect();
      if (!viewer.isDestroyed()) {
        viewer.destroy();
      }
    },
  };
}

function addTrack(viewer: Viewer, track: TrackPoint[], color: string, width: number) {
  if (track.length < 2) {
    return;
  }
  viewer.entities.add({
    polyline: {
      positions: track.map((fix) => toCartesian(fix)),
      width,
      material: Color.fromCssColorString(color),
      arcType: ArcType.NONE,
    },
  });
}

function toCartesian(fix: TrackPoint | null): Cartesian3 {
  if (!fix) {
    return Cartesian3.fromDegrees(0, 0, 400_000);
  }
  return Cartesian3.fromDegrees(fix.longitudeDeg, fix.latitudeDeg, fix.heightKm * 1000);
}
