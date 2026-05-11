/// Центральний HTTP-клієнт до FastAPI бекенду.
///
/// Іменування `apiClient` свідомо узгоджене з Office-проєктом — щоб уся
/// мережева логіка йшла через один інстанс (легше додати auth header,
/// логування, retry, тощо).
library;

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

class ApiClient {
  ApiClient({String baseUrl = 'http://127.0.0.1:8765'})
      : _dio = Dio(
          BaseOptions(
            baseUrl: baseUrl,
            connectTimeout: const Duration(seconds: 10),
            receiveTimeout: const Duration(seconds: 60),
            sendTimeout: const Duration(seconds: 60),
            headers: {'Accept': 'application/json'},
            // Не кидаємо exception на 4xx — обробляємо у викликаючому коді.
            validateStatus: (status) => status != null && status < 500,
          ),
        ) {
    _dio.interceptors.add(_LoggingInterceptor());
  }

  final Dio _dio;
  Dio get raw => _dio;

  /// Замінити baseUrl під час runtime (наприклад при підключенні до іншого сервера).
  void setBaseUrl(String url) {
    _dio.options.baseUrl = url;
  }

  // ─── GET helpers ──────────────────────────────────────────────

  Future<Response<T>> get<T>(String path, {Map<String, dynamic>? query}) {
    return _dio.get<T>(path, queryParameters: query);
  }

  Future<Response<T>> post<T>(String path,
      {dynamic data, Map<String, dynamic>? query}) {
    return _dio.post<T>(path, data: data, queryParameters: query);
  }

  Future<Response<T>> patch<T>(String path, {dynamic data}) {
    return _dio.patch<T>(path, data: data);
  }

  Future<Response<T>> delete<T>(String path) {
    return _dio.delete<T>(path);
  }

  /// Multipart upload — для виписок і вивантажень УНФ.
  Future<Response<T>> upload<T>(
    String path, {
    required String fieldName,
    required String filePath,
    required String filename,
    required Map<String, dynamic> data,
  }) async {
    final form = FormData.fromMap({
      ...data,
      fieldName: await MultipartFile.fromFile(filePath, filename: filename),
    });
    return _dio.post<T>(path, data: form);
  }
}

class _LoggingInterceptor extends Interceptor {
  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    debugPrint('→ ${options.method} ${options.uri}');
    handler.next(options);
  }

  @override
  void onResponse(Response response, ResponseInterceptorHandler handler) {
    debugPrint('← ${response.statusCode} ${response.requestOptions.uri}');
    handler.next(response);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    debugPrint('✗ ${err.requestOptions.uri}: ${err.message}');
    handler.next(err);
  }
}
