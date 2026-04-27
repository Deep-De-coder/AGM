declare module "d3-force-3d" {
  export interface SimulationNodeDatum {
    index?: number;
    x: number;
    y: number;
    z: number;
    vx?: number;
    vy?: number;
    vz?: number;
    fx?: number | null;
    fy?: number | null;
    fz?: number | null;
  }

  export interface SimulationLinkDatum<N extends SimulationNodeDatum> {
    source: string | N;
    target: string | N;
    index?: number;
  }

  export interface Force<N extends SimulationNodeDatum> {
    (alpha: number): void;
    initialize?(nodes: N[], random: () => number): void;
  }

  export interface ForceLink<N extends SimulationNodeDatum, L extends SimulationLinkDatum<N>>
    extends Force<N> {
    links(): L[];
    links(links: L[]): this;
    id(fn: (node: N, i: number, nodesData: N[]) => string): this;
    distance(d: number | ((link: L) => number)): this;
    strength(s: number | ((link: L) => number)): this;
  }

  export interface ForceManyBody<N extends SimulationNodeDatum> extends Force<N> {
    strength(s: number | ((d: N, i: number) => number)): this;
  }

  export interface ForceAxis<N extends SimulationNodeDatum> extends Force<N> {
    strength(s: number | ((d: N, i: number) => number)): this;
  }

  export interface Simulation<N extends SimulationNodeDatum> {
    restart(): this;
    stop(): this;
    tick(iterations?: number): this;
    nodes(): N[];
    nodes(nodes: N[]): this;
    alpha(): number;
    alpha(alpha: number): this;
    alphaMin(min: number): this;
    velocityDecay(decay: number): this;
    force(name: string): Force<N> | undefined;
    force(name: string, force: Force<N> | null): this;
    numDimensions(n: number): this;
    on(typenames: string, listener: () => void): this;
  }

  export function forceSimulation<N extends SimulationNodeDatum>(nodes?: N[]): Simulation<N>;

  export function forceLink<N extends SimulationNodeDatum, L extends SimulationLinkDatum<N>>(
    links?: L[],
  ): ForceLink<N, L>;

  export function forceManyBody<N extends SimulationNodeDatum>(): ForceManyBody<N>;

  export function forceCenter<N extends SimulationNodeDatum>(
    x?: number,
    y?: number,
    z?: number,
  ): Force<N>;

  export function forceZ<N extends SimulationNodeDatum>(
    z?: number | ((d: N, i: number) => number),
  ): ForceAxis<N>;
}
