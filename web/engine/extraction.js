/**
 * 판독 결과 스키마 — 서버(AI 판독)와 클라이언트(변환·렌더) 사이의 계약.
 *
 * 저작권 설계상 서버가 돌려주는 것은 **표현물이 아니라 구조 데이터**여야 한다.
 * 좌표와 텍스트는 사실 정보이고, 이걸 악보 이미지로 합성하는 일은
 * 사용자 브라우저에서 일어난다.
 */

                              
                             
            
            
            
            
 

                                 
                                                         
               
                   
                                       
                     
 

                                   
                         
                
                                
               
                                         
                   
                      
                           
                                  
                 
 

                            
                 
                    
                    
                                  
              
                         
                                     
                     
                          
                    
 

                                  
                  
                              
                           
                                      
 

/** 신뢰도가 이 값 미만이면 사용자 확인을 붙인다 */
export const CONFIDENCE_THRESHOLD = 0.9;

/** 판독 전체에서 코드를 등장 순서대로 평탄화 */
export function flattenChords(ex                 )                   {
  return ex.systems.flatMap((s) => s.chords);
}

/** 사용자 확인이 필요한 코드 */
export function lowConfidence(
  ex                 ,
  threshold = CONFIDENCE_THRESHOLD,
)                   {
  return flattenChords(ex).filter((c) => c.confidence < threshold);
}

/** 판독에 쓰인 서로 다른 코드 표기 목록 */
export function uniqueChordTexts(ex                 )           {
  return [...new Set(flattenChords(ex).map((c) => c.text))];
}
