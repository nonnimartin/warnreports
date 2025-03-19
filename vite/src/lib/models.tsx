interface Partial {
  [x: string]: any
}
export interface Naic extends Partial {
  id: number
  depth: number
  title: string
}
export interface ReportData extends Partial {
  id: string
  company: string
  reported: string
  artifacts: Artifact[]
  naics: Naic[]
}
export interface Artifact extends Partial {
  id: string
  name: string
}
export interface FieldDef extends Partial {
  title: string
  type?: string
}
export interface FieldDefs {
  [name: string]: FieldDef
}
export interface ColDef extends Partial {
  title: string
  type?: string
  orderable?: boolean
}
export interface ColDefs {
  [name: string]: ColDef
}