import { useState } from 'react';
import axios from 'axios';
import { getErrorMessages } from '@/api/api';
import { importsApi } from '@/api/imports';
import type { DatasetFileReport, ImportFileType } from '@/api/types';

export type FileStatus = 'waiting' | 'uploading' | 'processing' | 'done' | 'failed'

export interface UploadItem {
  name: string
  status: FileStatus
  fileType?: ImportFileType | null
  accepted?: number
  rejected?: number
  message?: string
}

export interface UploadSummary {
  companies: number
  operations: number
  rejected: number
  skipped: number
  failedFiles: number
  companyIds: string[]
  tookMs: number
  items: UploadItem[]
}

const COMPANIES_HEADER_START = 'company_id;company_name;company_inn'
const NO_DATASET_ENDPOINT = [404, 405]
const ZIP_UNSUPPORTED = 'Сервер пока не принимает архивы. Распакуйте ZIP и выберите файлы CSV.'

const isZip = (file: File) => file.name.toLowerCase().endsWith('.zip')

/** Эндпоинта загрузки датасета на сервере нет — грузим по одному файлу. */
const isMissingEndpoint = (error: unknown) =>
  axios.isAxiosError(error) && NO_DATASET_ENDPOINT.includes(error.response?.status ?? 0)

const isCompaniesFile = async (file: File) => {
  const head = await file.slice(0, 1024).text()
  return head.replace(/^﻿/, '').startsWith(COMPANIES_HEADER_START)
}

const toItem = (report: DatasetFileReport): UploadItem => (report.error
  ? { name: report.name, status: 'failed', fileType: null, message: report.error }
  : { name: report.name, status: 'done', fileType: report.fileType, accepted: report.accepted, rejected: report.rejected })

const summarize = (items: UploadItem[], skipped: number, companyIds: string[], tookMs: number): UploadSummary => ({
  companies: items.filter((item) => item.fileType === 'COMPANIES').reduce((sum, item) => sum + (item.accepted ?? 0), 0),
  operations: items.filter((item) => item.fileType === 'OPERATIONS').reduce((sum, item) => sum + (item.accepted ?? 0), 0),
  rejected: items.reduce((sum, item) => sum + (item.rejected ?? 0), 0),
  skipped,
  failedFiles: items.filter((item) => item.status === 'failed').length,
  companyIds,
  tookMs,
  items,
})

export const useDatasetUpload = (onDone: (summary: UploadSummary) => void) => {
  const [items, setItems] = useState<UploadItem[]>([])
  const [progress, setProgress] = useState<number | null>(null)
  const [errors, setErrors] = useState<string[]>([])

  const updateItem = (index: number, patch: Partial<UploadItem>) =>
    setItems((current) => current.map((item, itemIndex) => (itemIndex === index ? { ...item, ...patch } : item)))

  const uploadAtOnce = async (files: File[], startedAt: number) => {
    setItems(files.map((file) => ({ name: file.name, status: 'uploading' })))
    const report = await importsApi.uploadDataset(files, (percent) => {
      setProgress(percent)
      if (percent >= 100) {
        setItems((current) => current.map((item) => ({ ...item, status: 'processing' })))
      }
    })
    const done = report.files.map(toItem)
    setItems(done)
    onDone(summarize(done, report.skipped, report.companyIds, performance.now() - startedAt))
  }

  const uploadOneByOne = async (files: File[], startedAt: number) => {
    if (files.some(isZip)) {
      setItems(files.map((file) => (isZip(file)
        ? { name: file.name, status: 'failed', message: ZIP_UNSUPPORTED }
        : { name: file.name, status: 'waiting' })))
      setErrors([ZIP_UNSUPPORTED])
      return
    }
    // Справочник компаний первым: операции принимаются только по уже загруженным компаниям
    const flags = await Promise.all(files.map(isCompaniesFile))
    const ordered = [...files.filter((_, index) => flags[index]), ...files.filter((_, index) => !flags[index])]
    const totalBytes = ordered.reduce((sum, file) => sum + file.size, 0) || 1
    const result: UploadItem[] = ordered.map((file) => ({ name: file.name, status: 'waiting' }))
    setItems(result)
    const companyIds = new Set<string>()
    let skipped = 0
    let loadedBytes = 0
    for (const [index, file] of ordered.entries()) {
      updateItem(index, { status: 'uploading' })
      try {
        const report = await importsApi.upload(file, (percent) => {
          setProgress(Math.round(((loadedBytes + (file.size * percent) / 100) * 100) / totalBytes))
          if (percent >= 100) {
            updateItem(index, { status: 'processing' })
          }
        })
        result[index] = { name: file.name, status: 'done', fileType: report.fileType, accepted: report.accepted,
          rejected: report.rejected }
        skipped += report.skipped
        report.companyIds?.forEach((id) => companyIds.add(id))
      } catch (error) {
        result[index] = { name: file.name, status: 'failed', message: getErrorMessages(error).join(' ') }
      }
      updateItem(index, result[index])
      loadedBytes += file.size
    }
    onDone(summarize(result, skipped, [...companyIds].sort(), performance.now() - startedAt))
  }

  const upload = async (files: File[]) => {
    setErrors([])
    setProgress(0)
    const startedAt = performance.now()
    try {
      await uploadAtOnce(files, startedAt)
    } catch (error) {
      if (isMissingEndpoint(error)) {
        await uploadOneByOne(files, startedAt)
      } else {
        setItems((current) => current.map((item) => ({ ...item, status: 'failed' })))
        setErrors(getErrorMessages(error))
      }
    } finally {
      setProgress(null)
    }
  }

  return { items, progress, errors, upload, isUploading: progress !== null }
}
